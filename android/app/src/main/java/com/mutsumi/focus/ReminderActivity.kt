package com.mutsumi.focus

import android.content.Context
import android.content.Intent
import android.content.res.Configuration
import android.graphics.Color
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import java.lang.ref.WeakReference

/** Opaque, non-exported UI. Android Home, Recents and the lock screen stay available. */
class ReminderActivity : ComponentActivity() {
    private lateinit var store: PopupReminderStore
    private var duration = 0
    private var selecting = false
    private var question: ReminderQuestion? = null
    private var reviewingAnswer = false
    private var submitting = false
    private var bankSyncFailed = false
    private val required: Boolean get() = store.pending.isNotBlank()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        store = PopupReminderStore(this)
        duration = savedInstanceState?.getInt("minutes") ?: intent.getIntExtra(EXTRA_DURATION, 0)
        selecting = savedInstanceState?.getBoolean("selecting") ?: (intent.action == ACTION_CHALLENGE)
        reviewingAnswer = savedInstanceState?.getBoolean("reviewing_answer") ?: false
        question = savedInstanceState?.let { state ->
            val body = state.getString("body") ?: return@let null
            val options = state.getStringArrayList("options") ?: return@let null
            ReminderQuestion(body, options, state.getInt("answer"))
        }
        if (savedInstanceState == null && duration > 0 && store.delayWithoutQuestion(duration, System.currentTimeMillis())) {
            FocusService.reminderSettingsChanged(this); finish(); return
        }
        if (duration !in store.muteOptions) { duration = 0; question = null }
        else if (question == null) question = nextQuestion()
        reviewingAnswer = reviewingAnswer && question != null
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (!required) finish()
            }
        })
        if (intent.action == ACTION_SHOW && !required && !selecting) { finish(); return }
        window.setBackgroundDrawableResource(android.R.color.white)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        window.isStatusBarContrastEnforcedCompat()
        render(animate = savedInstanceState == null)
        if (duration > 0 && question == null) syncQuestion() else ReminderBankSync.refresh(this)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        if (intent.action == ACTION_CHALLENGE) {
            setIntent(intent)
            val minutes = intent.getIntExtra(EXTRA_DURATION, 0)
            if (minutes in store.muteOptions) choose(minutes) else if (question == null) { selecting = true; render() }
        }
    }

    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        if (!isFinishing) render()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        outState.putInt("minutes", duration)
        outState.putBoolean("selecting", selecting)
        outState.putBoolean("reviewing_answer", reviewingAnswer)
        question?.let {
            outState.putString("body", it.body); outState.putStringArrayList("options", ArrayList(it.options)); outState.putInt("answer", it.answer)
        }
        super.onSaveInstanceState(outState)
    }

    override fun onResume() {
        super.onResume()
        active = WeakReference(this)
        if (!required && !selecting) finish() else FocusService.requestReminderCheck(this)
    }

    override fun onPause() {
        if (active?.get() === this) active = null
        super.onPause()
    }

    private fun nextQuestion() = ReminderQuestions.next(ReminderQuestions.decode(store.bankJson), question)

    private fun syncQuestion() {
        ReminderBankSync.refresh(this) { count ->
            if (isFinishing || isDestroyed || duration <= 0 || question != null) return@refresh
            bankSyncFailed = count == null
            question = nextQuestion()
            render()
        }
    }

    private fun choose(minutes: Int, extraMinute: Boolean = false) {
        if (store.delayWithoutQuestion(minutes, System.currentTimeMillis(), extraMinute)) {
            FocusService.reminderSettingsChanged(this)
            finish()
            return
        }
        if (extraMinute || minutes !in store.muteOptions) return
        duration = minutes; selecting = true; reviewingAnswer = false; question = nextQuestion()
        bankSyncFailed = false
        render(true)
        if (question == null) syncQuestion()
    }

    private fun answer(index: Int) {
        if (submitting || reviewingAnswer) return
        val current = question ?: return
        if (index != current.answer) {
            reviewingAnswer = true; render(true); return
        }
        submitting = true
        store.mute(duration, System.currentTimeMillis())
        FocusService.reminderSettingsChanged(this)
        finish()
    }

    private fun advance() {
        if (!reviewingAnswer) return
        question = nextQuestion()
        reviewingAnswer = false
        render(true)
    }

    private fun changeDuration() {
        duration = 0; question = null; selecting = true; reviewingAnswer = false
        render(true)
    }

    private fun render(animate: Boolean = false) {
        val runtime = FocusStateStore(this).read()
        val style = ReminderUi(this, OriginOsAtomicPublisher(this).palette(runtime).accent)
        val root = FrameLayout(this).apply { setBackgroundColor(Color.WHITE) }
        val wide = resources.configuration.screenWidthDp >= 600
        val compact = resources.configuration.screenHeightDp < 420
        val contents = style.vertical().apply {
            setPadding(style.dp(16), style.dp(if (compact) 10 else 16), style.dp(16), style.dp(if (compact) 10 else 16))
        }
        val label = if (duration > 0) "验证 · 静默 $duration 分钟" else if (selecting) "专注 · 静默提醒" else "M  /  专注提醒"
        style.add(contents, style.tag(label))
        contents.addView(View(this).apply { setBackgroundColor(style.border) }, LinearLayout.LayoutParams(-1, style.dp(1)).apply {
            topMargin = style.dp(if (compact) 5 else 10)
        })
        if (question != null) {
            val item = question ?: return
            if (reviewingAnswer) style.revealedAnswer(contents, item, compact = compact)
            else {
                style.add(contents, style.label("答对一题，暂停提醒", if (compact) 19f else 22f, bold = true), 6)
                style.quiz(contents, item, compact = false, wide = wide && resources.configuration.fontScale <= 1.25f) { index ->
                    if (question === item) answer(index)
                }
                style.add(contents, style.button("更改静默时长", compact = true, action = ::changeDuration), 7)
            }
        } else if (duration > 0) {
            style.unavailableBank(contents, store.bankJson.isNotBlank(), bankSyncFailed, ::syncQuestion, ::changeDuration)
        } else {
            val pause = runtime.mode == FocusMode.PAUSED
            style.add(contents, style.label(when { selecting -> "关闭提醒一段时间"; pause -> "准备好，继续专注"; else -> "回到下一段专注" },
                if (compact) 22f else 26f, bold = true), 7)
            style.add(contents, style.label(when { selecting -> "选择一段时间，稍后再提醒。";
                pause -> "本段计时仍在暂停，回到计时页后可继续。"; else -> "回到计时页选一个事项。开始后，本次提醒结束。" }, 13f, style.muted), 4)
            if (!selecting) style.add(contents, style.button("回到专注", true) {
                if (!required) { finish(); return@button }
                store.returnToFocus()
                FocusService.reminderSettingsChanged(this)
                startActivity(Intent(this, MainActivity::class.java)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
                    .putExtra("focus_destination", if (pause) "resumeFocus" else "next"))
                finish()
            }, if (compact) 10 else 18)
            style.add(contents, style.tag("关闭所有提醒"), if (compact) 9 else 17)
            style.delayChoices(contents, store, compact = compact, onChoose = { choose(it) }, onExtraMinute = { choose(1, true) })
            if (selecting) style.add(contents, style.button(if (required) "返回提醒" else "取消") {
                if (!required) finish() else { selecting = false; render(true) }
            }, 8)
        }
        val card = if (reviewingAnswer) {
            style.reviewCard(contents, compact = false, onNext = ::advance, onChangeDuration = ::changeDuration)
        } else contents
        card.background = style.surface(Color.WHITE, 10, style.border)
        card.clipToOutline = true
        val viewport = FrameLayout(this).apply {
            setPadding(style.dp(16), style.dp(10), style.dp(16), style.dp(10))
            addView(card, FrameLayout.LayoutParams(minOf(style.dp(if (wide) 680 else 440),
                style.dp((resources.configuration.screenWidthDp - 36).coerceAtLeast(160))), -2, Gravity.CENTER))
        }
        if (reviewingAnswer) root.addView(viewport)
        else root.addView(ScrollView(this).apply { isFillViewport = true; clipToPadding = false; addView(viewport) })
        setContentView(root)
        WindowCompat.getInsetsController(window, root).apply {
            isAppearanceLightStatusBars = true; isAppearanceLightNavigationBars = true
        }
        ViewCompat.setOnApplyWindowInsetsListener(root) { view, insets ->
            val safe = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout())
            view.setPadding(safe.left, safe.top, safe.right, safe.bottom)
            insets
        }
        ViewCompat.requestApplyInsets(root)
        if (animate) {
            card.alpha = 0f; card.translationY = style.dp(8).toFloat()
            card.animate().alpha(1f).translationY(0f).setDuration(200).start()
        }
    }

    @Suppress("DEPRECATION")
    private fun android.view.Window.isStatusBarContrastEnforcedCompat() {
        if (android.os.Build.VERSION.SDK_INT >= 29) { isStatusBarContrastEnforced = false; isNavigationBarContrastEnforced = false }
    }

    companion object {
        private const val ACTION_SHOW = "com.mutsumi.focus.POPUP_REMINDER"
        private const val ACTION_CHALLENGE = "com.mutsumi.focus.MUTE_CHALLENGE"
        private const val EXTRA_DURATION = "mute_duration"
        private var active: WeakReference<ReminderActivity>? = null
        fun visible(): Boolean = active?.get()?.isFinishing == false
        fun resolved() { active?.get()?.let { if (!it.selecting && !it.required) it.finish() } }
        fun dismiss() { active?.get()?.finish() }
        fun intent(context: Context, challenge: Boolean = false, duration: Int = 0): Intent =
            Intent(context, ReminderActivity::class.java).setAction(if (challenge) ACTION_CHALLENGE else ACTION_SHOW)
                .putExtra(EXTRA_DURATION, duration).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
    }
}
