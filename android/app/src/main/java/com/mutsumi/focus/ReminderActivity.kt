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
import android.widget.TextView
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
    private var wrong = false
    private var submitting = false
    private val required: Boolean get() = store.pending.isNotBlank()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        store = PopupReminderStore(this)
        duration = savedInstanceState?.getInt("minutes") ?: intent.getIntExtra(EXTRA_DURATION, 0)
        selecting = savedInstanceState?.getBoolean("selecting") ?: (intent.action == ACTION_CHALLENGE)
        wrong = savedInstanceState?.getBoolean("wrong") ?: false
        question = savedInstanceState?.let { state ->
            val body = state.getString("body") ?: return@let null
            val options = state.getStringArrayList("options") ?: return@let null
            ReminderQuestion(body, options, state.getInt("answer"))
        }
        if (duration in store.muteOptions && question == null) question = nextQuestion()
        else if (duration !in store.muteOptions) { duration = 0; question = null }
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
        ReminderBankSync.refresh(this)
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
        outState.putBoolean("wrong", wrong)
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

    private fun choose(minutes: Int) {
        if (minutes !in store.muteOptions) return
        duration = minutes; selecting = true; wrong = false; question = nextQuestion()
        render(true)
    }

    private fun answer(index: Int) {
        if (submitting) return
        val current = question ?: return
        if (index != current.answer) {
            wrong = true; question = nextQuestion(); render(true); return
        }
        submitting = true
        store.mute(duration, System.currentTimeMillis())
        FocusService.reminderSettingsChanged(this)
        finish()
    }

    private fun render(animate: Boolean = false) {
        val runtime = FocusStateStore(this).read()
        val style = ReminderUi(this, OriginOsAtomicPublisher(this).palette(runtime).accent)
        val root = FrameLayout(this).apply { setBackgroundColor(Color.WHITE) }
        val wide = resources.configuration.screenWidthDp >= 600
        val compact = resources.configuration.screenHeightDp < 420
        val contents = style.vertical().apply {
            setPadding(style.dp(20), style.dp(if (compact) 12 else 22), style.dp(20), style.dp(if (compact) 12 else 22))
            background = style.surface(Color.WHITE, 10, style.border)
        }
        val label = if (question != null) "验证 · 静默 $duration 分钟" else if (selecting) "专注 · 静默提醒" else "M  /  专注提醒"
        style.add(contents, style.tag(label))
        contents.addView(View(this).apply { setBackgroundColor(style.border) }, LinearLayout.LayoutParams(-1, style.dp(1)).apply {
            topMargin = style.dp(if (compact) 5 else 10)
        })
        if (question != null) {
            val item = question ?: return
            val upper = style.vertical()
            val options = style.vertical()
            style.add(upper, style.label("答对一题，暂停提醒", if (compact) 23f else 28f, bold = true))
            if (wrong) style.add(upper, style.label("这题答错了，试试下面这道。", 13f, 0xffa3342b.toInt()).apply {
                accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
            }, 4)
            val body = style.vertical()
            style.question(body, item.body)
            style.add(upper, body, 10)
            for ((index, option) in item.options.withIndex()) {
                val letter = ('A' + index).toString()
                style.add(options, style.button("$letter   ${ReminderMath.inline(option)}") { answer(index) }.apply {
                    gravity = Gravity.CENTER_VERTICAL or Gravity.START; setPadding(style.dp(15), 0, style.dp(10), 0)
                }, if (index == 0) 0 else 6)
            }
            if (wide) style.add(contents, LinearLayout(this).apply {
                addView(upper, LinearLayout.LayoutParams(0, -2, 1.25f))
                addView(options, LinearLayout.LayoutParams(0, -2, 1f).apply { marginStart = style.dp(18) })
            }, 10) else { style.add(contents, upper, 12); style.add(contents, options, 13) }
            style.add(contents, style.button("更改静默时长") { duration = 0; question = null; selecting = true; wrong = false; render(true) }, 9)
        } else {
            val pause = runtime.mode == FocusMode.PAUSED
            style.add(contents, style.label(when { selecting -> "关闭提醒一段时间"; pause -> "准备好，继续专注"; else -> "回到下一段专注" },
                if (compact) 26f else 34f, bold = true), if (compact) 6 else 13)
            style.add(contents, style.label(when { selecting -> "选一个时长，答对一道题后生效。";
                pause -> "本段计时仍在暂停，回到计时页后可继续。"; else -> "回到计时页选一个事项。开始后，本次提醒结束。" }, 15f, style.muted), 6)
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
            style.add(contents, style.durations(store.muteOptions, ::choose), 5)
            if (selecting) style.add(contents, style.button(if (required) "返回提醒" else "取消") {
                if (!required) finish() else { selecting = false; render(true) }
            }, 8)
        }
        val viewport = FrameLayout(this).apply {
            setPadding(style.dp(16), style.dp(10), style.dp(16), style.dp(10))
            addView(contents, FrameLayout.LayoutParams(minOf(style.dp(if (wide) 680 else 440),
                style.dp((resources.configuration.screenWidthDp - 36).coerceAtLeast(160))), -2, Gravity.CENTER))
        }
        root.addView(ScrollView(this).apply { isFillViewport = true; clipToPadding = false; addView(viewport) })
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
            contents.alpha = 0f; contents.translationY = style.dp(8).toFloat()
            contents.animate().alpha(1f).translationY(0f).setDuration(200).start()
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
