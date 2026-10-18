"""Deterministic single-tick executions, driven by causal focus/value inputs.

The model consumes at most one price-level order per 100 ms. Minute samples
are summaries of executions, never targets which the browser interpolates.
"""
from collections import deque, OrderedDict
from dataclasses import dataclass
from bisect import bisect_right
import hashlib
import json
import math
import random
from threading import RLock
from typing import Callable

MODEL = "focus-exchange-v1"
ENGINE_REVISION = 3
TICK = 0.001
INTERVAL_MS = 100


@dataclass(frozen=True)
class ExchangeParameters:
    support_percent: float = 1.2
    resistance_percent: float = 1.2
    switch_minutes: float = 8.0
    switch_return: float = 0.0015
    # Preserve ordinary market motion independently of the gentler switches.
    noise_volatility: float = 0.009
    value_relaxation_seconds: float = 45.0
    reversion_strength: float = 0.35
    reversion_response_seconds: float = 120.0

    def __post_init__(self):
        for name in ("support_percent", "resistance_percent"):
            value = getattr(self, name)
            if not math.isfinite(value) or not 0.2 <= value <= 5:
                raise ValueError(f"invalid_{name}")
        if not math.isfinite(self.switch_minutes) or not 5 <= self.switch_minutes <= 10:
            raise ValueError("invalid_switch_minutes")
        dynamics = (self.switch_return,self.value_relaxation_seconds,self.noise_volatility,
                    self.reversion_strength,self.reversion_response_seconds)
        if (not all(math.isfinite(v) for v in dynamics) or self.switch_return < 0
                or self.value_relaxation_seconds <= 0 or self.noise_volatility < 0
                or self.reversion_strength < 0 or self.reversion_response_seconds <= 0):
            raise ValueError("invalid_exchange_dynamics")

    @classmethod
    def from_settings(cls, settings):
        values = settings or {}
        return cls(**{name:float(values.get("focus_kline_" + name, default))
                      for name, default in (("support_percent",1.2),("resistance_percent",1.2),("switch_minutes",8))})

    def public(self):
        return {"support_percent":self.support_percent, "resistance_percent":self.resistance_percent,
                "switch_minutes":self.switch_minutes, "price_tick":TICK, "minimum_trade_interval_ms":INTERVAL_MS}


@dataclass(frozen=True)
class BookInput:
    active: bool
    session: str
    focusing: bool
    value: float
    reference: float
    lower: float
    upper: float
    taper: float = 1.0
    opening: float | None = None
    bar_origin_ms: int | None = None


class PriceBook:
    def __init__(self, start_ms: int, price: float, seed: int, parameters=None, *, record_trades=False):
        self.parameters = parameters or ExchangeParameters()
        self.at_ms = int(start_ms) // INTERVAL_MS * INTERVAL_MS
        self.units = round(price / TICK)
        self.rng = random.Random(seed)
        self.noise_rng = random.Random(seed ^ 0x5A17C3)
        self.momentum = self.noise = self.pending_switch = 0.0
        self.reversion_momentum = 0.0
        self.switch_remaining = 0.0
        self.previous_focusing = None
        self.previous_session = None
        self.previous_second = None
        self.direction = 0
        self.last_trade_ms = None
        self.trades = deque(maxlen=200)
        self.all_trades = [] if record_trades else None
        self.samples = []
        self.high = self.low = self.price
        self.minute_high = self.minute_low = self.price
        self.value = self.support = self.resistance = self.price
        self.executions = self.visited_slots = 0
        self.source_signature = None
        self.last_input = None
        self.last_active_ms = None

    @property
    def price(self):
        return round(self.units * TICK, 3)

    def _sample(self, at_ms, inputs, **extra):
        self.samples.append({"timestamp_ms":at_ms,"price":self.price,"state":"focus" if inputs.focusing else "idle",
                             "session":inputs.session,"changed":False,"high":self.minute_high,"low":self.minute_low,
                             "value":round(self.value,3),"support":round(self.support,3),
                             "resistance":round(self.resistance,3),
                             "reversion_momentum":round(self.reversion_momentum,9),**extra})
        if not extra:
            self.minute_high = self.minute_low = self.price

    def _value_pressure(self, inputs):
        """Continuous opposing pressure, deepening across successive zones.

        The configured distances mark where pressure starts, not a price cap.
        Each further zone adds more opposing orders. No zone rejects a trade.
        """
        deviation = (self.price-inputs.value)/max(TICK,inputs.reference)
        width = (self.parameters.resistance_percent if deviation>=0
                 else self.parameters.support_percent)/100
        depth = max(0,abs(deviation)/width-1)
        layers = min(depth,1)+2*min(max(0,depth-1),1)+4*max(0,depth-2)
        return -math.copysign(width*self.parameters.reversion_strength*layers,deviation)

    def advance(self, until_ms: int, input_at: Callable[[int], BookInput]):
        until = int(until_ms) // INTERVAL_MS * INTERVAL_MS
        p = self.parameters
        # Updating pressure once per second keeps cold replay affordable. The
        # order matching itself uses ten deterministic slots every second.
        decay = 0.82 ** (1 / 600)
        noise_decay = 0.58 ** (1 / 600)
        noise_sigma = p.noise_volatility / math.sqrt(600)
        reversion_response = -math.expm1(-1/p.reversion_response_seconds)
        while self.at_ms < until:
            at = self.at_ms + INTERVAL_MS
            second = at // 1000
            if second != self.previous_second or self.last_input is None:
                inputs = input_at(second * 1000)
                previous_input = self.last_input
                if previous_input is not None and previous_input.active and (
                        not inputs.active or inputs.session != previous_input.session):
                    # Preserve the last execution at the exact session boundary.
                    # No matching or random draw happens in a market break.
                    self._sample(second * 1000, previous_input, session_close=True)
                self.last_input = inputs
                self.previous_second = second
                if inputs.active:
                    if inputs.session != self.previous_session:
                        if self.last_active_ms is not None:
                            gap=max(0,(second*1000-self.last_active_ms)/1000)
                            self.momentum*=0.82**(gap/600)
                            self.noise*=0.58**(gap/600)
                            self.reversion_momentum*=math.exp(-gap/p.reversion_response_seconds)
                            if self.switch_remaining>0:
                                self.pending_switch*=max(0,1-gap/self.switch_remaining)
                                self.switch_remaining=max(0,self.switch_remaining-gap)
                        if inputs.opening is not None:
                            self.units = round(inputs.opening / TICK)
                            self.minute_high = self.minute_low = self.price
                            self.high = max(self.high,self.price); self.low = min(self.low,self.price)
                        self.previous_session = inputs.session
                        self.previous_focusing = inputs.focusing
                        self.value = inputs.value
                        self.support = inputs.value - inputs.reference*p.support_percent/100
                        self.resistance = inputs.value + inputs.reference*p.resistance_percent/100
                        if inputs.opening is not None:
                            self._sample(second*1000,inputs,opening_auction=True)
                    elif self.previous_focusing != inputs.focusing:
                        # Opposing unfilled pressure cancels; a rapid toggle
                        # cannot accumulate an unbounded queue of switch orders.
                        sign = 1 if inputs.focusing else -1
                        self.pending_switch = max(-p.switch_return,min(p.switch_return,self.pending_switch+sign*p.switch_return))
                        self.switch_remaining = p.switch_minutes*60
                        self.previous_focusing = inputs.focusing
                        self._sample(second*1000,inputs,changed=True)
                    release = self.pending_switch / max(1,self.switch_remaining) if self.switch_remaining>0 else 0
                    self.pending_switch -= release
                    self.switch_remaining = max(0,self.switch_remaining-1)
                    sign = 1 if inputs.focusing else -1
                    self.momentum = self.momentum*decay + sign*0.0036/600*0.9 + release
                    self.noise = self.noise*noise_decay+self.noise_rng.gauss(0,noise_sigma)
                    self.value = inputs.value
                    self.support = inputs.value-inputs.reference*p.support_percent/100
                    self.resistance = inputs.value+inputs.reference*p.resistance_percent/100
                    # Crossing a zone adds opposing momentum gradually; the
                    # original pressure can still carry trades farther out.
                    self.reversion_momentum += reversion_response*(self._value_pressure(inputs)-self.reversion_momentum)
                    displacement = (self.momentum+self.noise+self.reversion_momentum)*inputs.taper
                    self.target = inputs.value+inputs.reference*displacement
                    self.lower_units = math.ceil((inputs.lower-1e-9)/TICK)
                    self.upper_units = math.floor((inputs.upper+1e-9)/TICK)
            inputs = self.last_input
            if not inputs.active:
                # No random draws or transactions during a market break.
                self.at_ms = min(until,(second+1)*1000-INTERVAL_MS)
                continue
            self.visited_slots += 1
            self.at_ms = at
            self.last_active_ms=at
            net_rate = (self.target-self.price)/p.value_relaxation_seconds/TICK
            total_rate = abs(net_rate)+0.6
            if self.rng.random() < min(1.0,total_rate*INTERVAL_MS/1000):
                direction = 1 if self.rng.random() < (1+net_rate/total_rate)/2 else -1
                next_units=self.units+direction
                if direction and self.lower_units<=next_units<=self.upper_units:
                    self.units=next_units
                    self.direction=direction; self.last_trade_ms=at
                    self.executions+=1
                    trade={"id":at//INTERVAL_MS,"timestamp_ms":at,"price":self.price,"direction":direction,"session":inputs.session}
                    self.trades.append(trade)
                    if self.all_trades is not None: self.all_trades.append(trade)
                    self.high=max(self.high,self.price); self.low=min(self.low,self.price)
                    self.minute_high=max(self.minute_high,self.price); self.minute_low=min(self.minute_low,self.price)
            if (at-(inputs.bar_origin_ms or 0))%60000==0:
                self._sample(at,inputs)
        return self

    def snapshot(self):
        return {"model":MODEL,"price":self.price,"timestamp_ms":self.at_ms,"session":self.previous_session,
                "direction":self.direction,"last_trade_ms":self.last_trade_ms,
                "value":round(self.value,3),"support":round(self.support,3),"resistance":round(self.resistance,3),
                "reversion_momentum":round(self.reversion_momentum,9),
                "high":self.high,"low":self.low,"execution_count":self.executions,
                "trades":[dict(t) for t in self.trades if t['timestamp_ms']>=self.at_ms-20000],"samples":[dict(p) for p in self.samples],
                "parameters":self.parameters.public()}


class FocusClock:
    """Prefix integrals of effective focus, including overlapping imports."""
    def __init__(self, segments):
        self.segments=[(s.timestamp(),e.timestamp()) for s,e in segments if e>s]
        changes={}
        for start,end in self.segments:
            changes[start]=changes.get(start,0)+1
            changes[end]=changes.get(end,0)-1
        self.times=sorted(changes)
        self.counts=[]; self.totals=[]
        count=total=0; previous=self.times[0] if self.times else 0
        for at in self.times:
            total+=(at-previous)*count
            count+=changes[at]
            self.totals.append(total); self.counts.append(count); previous=at

    def total(self, at):
        index=bisect_right(self.times,at)-1
        return 0.0 if index<0 else self.totals[index]+(at-self.times[index])*self.counts[index]

    def focusing(self,at):
        index=bisect_right(self.times,at)-1
        return index>=0 and self.counts[index]>0

    def signature(self,at):
        clipped=[(s,min(e,at)) for s,e in self.segments if s<at]
        return hashlib.sha256(json.dumps(clipped,separators=(',',':')).encode()).hexdigest()


_BOOKS=OrderedDict()
_BOOK_LOCK=RLock()


def simulate_day(*, windows, segments, cutoff, start, price, reference, market_open,
                 lunch_gap, legacy, user_key, parameters, fundamental, config_key,
                 limit_events=(), activation=None, aggregate_focus_seconds=None):
    """Resume a cached deterministic book; source corrections rebuild it.

    The cache changes cost, not results. It retains only a day's minute
    summaries and 20 seconds of executions. A worker restart reproduces both.
    """
    clock=FocusClock(segments)
    starts=[w['start'].timestamp() for w in windows]
    ends=[w['end'].timestamp() for w in windows]
    names=[w['name'] for w in windows]
    durations=[e-s for s,e in zip(starts,ends)]
    total_market=sum(durations)
    day_start=windows[0]['start'].replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
    initial_ms=math.ceil(start.timestamp()*1000/INTERVAL_MS)*INTERVAL_MS
    until_ms=int(min(cutoff.timestamp(),ends[-1])*1000)
    limit_times=[at.timestamp() for at,_ in limit_events]
    limits=[value for _,value in limit_events]
    activation_at=activation.timestamp() if activation else None
    key=(str(user_key),initial_ms,round(price,3),reference,market_open,tuple(starts),tuple(ends),
         tuple(zip(limit_times,limits)),parameters,config_key)
    def policy(at):
        index=bisect_right(limit_times,at)-1
        return limits[index] if index>=0 else 0.10
    with _BOOK_LOCK:
        book=_BOOKS.get(key)
        if book is None or book.at_ms>until_ms or (book.source_signature is not None and book.source_signature!=clock.signature(book.at_ms/1000)):
            seed=int.from_bytes(hashlib.sha256(f'{user_key}:{initial_ms}:{MODEL}'.encode()).digest()[:8],'big')
            book=PriceBook(initial_ms,price,seed,parameters)
            book.origins={}
            book.checkpoint=None
            _BOOKS[key]=book
        _BOOKS.move_to_end(key)
        while len(_BOOKS)>32: _BOOKS.popitem(last=False)
        def inputs(ms):
            at=ms/1000
            index=bisect_right(starts,at)-1
            active=index>=0 and at<ends[index]
            if not active:
                return BookInput(False,'break',False,book.value,reference,reference*.9,reference*1.1)
            opening=None
            if index not in book.origins:
                if index==0:
                    origin=market_open
                else:
                    historical=next((p['price'] for p in legacy if p['session']==names[index]),None)
                    origin=historical if historical is not None else book.price*(1+lunch_gap)
                limit=policy(starts[index])
                origin=round(max(reference*(1-limit),min(reference*(1+limit),origin)),3)
                book.origins[index]=origin
                if starts[index]>=initial_ms/1000: opening=origin
            elapsed=sum(durations[:index])+(at-starts[index])
            market_focus=sum(clock.total(min(at,e))-clock.total(s) for s,e in zip(starts,ends) if at>s)
            off_focus=max(0,clock.total(at)-clock.total(day_start)-market_focus)
            projected=off_focus+(market_focus*total_market/max(1,elapsed)) if aggregate_focus_seconds is None else aggregate_focus_seconds
            hours=max(0,min(24,projected/3600))
            origin_return=book.origins[index]/reference-1
            remaining=total_market-sum(durations[:index])
            progress=(at-starts[index])/max(1,remaining)
            if activation_at and at>=activation_at:
                if book.checkpoint is None:
                    book.checkpoint=(book.price/reference-1,elapsed)
                baseline,checkpoint_elapsed=book.checkpoint
                actual=clock.total(at)-clock.total(day_start) if aggregate_focus_seconds is None else aggregate_focus_seconds
                activation_seconds=clock.total(activation_at)-clock.total(day_start) if aggregate_focus_seconds is None else aggregate_focus_seconds
                earned=fundamental(actual/3600,False,activation_seconds/3600)
                anchor=baseline+(elapsed-checkpoint_elapsed)/max(1,total_market-checkpoint_elapsed)*(earned-baseline)
            else:
                anchor=origin_return+progress*(fundamental(hours,policy(day_start)==.20,None)-origin_return)
            taper=min(1,((1-elapsed/total_market)/.08)**2)
            limit=policy(at)
            value=reference*(1+max(-limit,min(limit,anchor)))
            return BookInput(True,names[index],clock.focusing(at),value,reference,
                             round(reference*(1-limit),3),round(reference*(1+limit),3),taper,opening,int(starts[index]*1000))
        book.advance(until_ms,inputs)
        book.source_signature=clock.signature(book.at_ms/1000)
        return book.snapshot()
