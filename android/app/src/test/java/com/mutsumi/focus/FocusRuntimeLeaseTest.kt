package com.mutsumi.focus

import org.junit.Assert.*
import org.junit.Test

class FocusRuntimeLeaseTest {
    @Test fun `eight hour pause keeps CPU lease continuous without depending on notifications`() {
        var acquiredAt = -1L
        var deadline = -1L
        var renewals = 0
        for (now in 0L..8 * 3600_000L step 1000) {
            if (now > 0) assertTrue("lease expired at $now", now < deadline)
            if (FocusRuntimeLease.needsRenewal(now < deadline, acquiredAt, now)) {
                acquiredAt = now
                deadline = now + FocusRuntimeLease.TIMEOUT_MS
                renewals++
            }
        }
        assertEquals(61, renewals)
        assertTrue(FocusRuntimeLease.needsRenewal(false, acquiredAt, acquiredAt + 1))
    }

    @Test fun `resume after a suspended lunch requires restoration once not on ordinary ticks`() {
        assertFalse(FocusRuntimeLease.stalled(null, 0))
        assertFalse(FocusRuntimeLease.stalled(1000, 2000))
        assertTrue(FocusRuntimeLease.stalled(1000, 3 * 3600_000))
        assertFalse(FocusRuntimeLease.stalled(3 * 3600_000, 3 * 3600_000 + 1000))
    }

    @Test fun `background native heartbeat returns without accessing HTTP or cookies`() {
        assertNull(FocusApi.heartbeat(FocusRuntimeState(mode = FocusMode.FOCUSING, sessionId = 1), false))
        assertNull(FocusApi.heartbeat(FocusRuntimeState(mode = FocusMode.PAUSED, sessionId = 1), false))
    }
}
