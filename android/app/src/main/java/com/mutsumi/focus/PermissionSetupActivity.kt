package com.mutsumi.focus

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.net.Uri
import android.view.Gravity
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Switch
import android.widget.TextView
import android.widget.FrameLayout
import android.widget.EditText

class PermissionSetupActivity : Activity() {
    private lateinit var style: SetupStyle
    private lateinit var list: LinearLayout
    private lateinit var root: ScrollView
    private lateinit var store: FocusStateStore
    private lateinit var popup: PopupReminderStore
    private var unbindBlur: (() -> Unit)? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        store = FocusStateStore(this)
        popup = PopupReminderStore(this)
        store.setOnboardingSeen()
    }

    override fun onResume() {
        super.onResume()
        FocusService.setAppVisible(this, true)
        render()
    }

    private fun render() {
        val scroll = if (::root.isInitialized) root.scrollY else 0
        style = SetupStyle(this)
        unbindBlur?.invoke()
        unbindBlur = style.bindWindow(this)
        list = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(style.dp(18), style.dp(16), style.dp(18), style.dp(20))
        }
        label(list, "原子岛与提醒", 18f)
        label(list, "状态与计时始终一致。按需要开启功能，也可以稍后设置。", 12f)
        val atomic = card("原子岛展示")
        toggle(atomic, "在原子岛展示专注与休息", store.atomicEnabled()) {
            store.setAtomicEnabled(it)
            FocusService.requestReminderCheck(this)
        }
        val vivo = Build.MANUFACTURER.equals("vivo", true) || Build.BRAND.equals("iqoo", true) || Build.BRAND.equals("vivo", true)
        val enabled = if (vivo) runCatching {
            val manager = getSystemService(android.app.NotificationManager::class.java)
            manager.javaClass.getMethod("getSceneStatus", String::class.java, String::class.java)
                .invoke(manager, packageName, BuildConfig.VIVO_ATOMIC_SCENE) as Boolean
        }.getOrNull() else null
        label(atomic, if (!vivo) "当前设备使用 Android 实时状态通知。" else when (enabled) {
            true -> "场景授权已开启 · 展示形态由系统管理"
            false -> "场景尚未开启 · 普通通知可继续使用"
            null -> "暂无法读取场景授权 · 可进入引导检查"
        })
        if (vivo) button(atomic, "启用与撤销原子岛") {
            startActivity(Intent(this, AtomicIslandSetupActivity::class.java))
        }
        permission(atomic, "通知与状态操作", PermissionStatus.notifications(this), "允许计时、暂停、继续和结束操作。") {
            if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED)
                requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 40)
            else openSafely(Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, packageName))
        }
        if (Build.VERSION.SDK_INT >= 36) permission(atomic, "Android 实时通知", PermissionStatus.promotedNotifications(this), "系统允许时显示实时计时；普通通知仍保留。") {
            openSafely(Intent(Settings.ACTION_APP_NOTIFICATION_PROMOTION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, packageName))
        }
        val reminders = card("弹出式提醒")
        label(reminders, "开盘期间，未专注时持续显示边缘条。橙色表示等待，紫色表示一分钟内即将提醒。")
        label(reminders, "向内拉开，向外收起；可从展开卡片上向外滑动。沿屏幕边缘拖动可调整位置。")
        if (popup.pending.isBlank()) toggle(reminders, "启用边缘提示与全屏提醒", popup.enabled) {
            popup.enabled = it
            FocusService.reminderSettingsChanged(this)
            render()
        } else label(reminders, "请先开始专注或完成静默验证，再更改提醒规则。")
        label(reminders, "全屏只在亮屏解锁时打开。每段非专注期间，首次常规延迟直接生效，另有一次额外延迟 1 分钟；后续常规延迟需答对一道题。")
        if (popup.enabled) {
            permission(reminders, "显示在其他应用上层", PermissionStatus.overlay(this), "用于边缘色带和退到桌面后的提醒。") {
                openSafely(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName")))
            }
            permission(reminders, "无障碍边缘色带（可选）", PermissionStatus.accessibility(this), "只作边缘提示备用，不读取窗口内容。") {
                openSafely(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
            }
            if (popup.pending.isBlank()) button(reminders, "调整提醒时间与静默选项") { configureReminders() }
            label(reminders, "暂停：${threshold(popup.pauseMinutes)} · 闲置：${threshold(popup.idleMinutes)}\n静默选项：${popup.muteOptions.joinToString(" / ")} 分钟", 12f)
        }
        button(reminders, "关闭所有提醒一段时间") { startActivity(ReminderActivity.intent(this, challenge = true)) }
        val questions = card("验证题库")
        label(questions, "内置 ${ReminderQuestions.builtIn.size} 道题，覆盖极限、定积分、级数和基础口算。可由 Agent 维护自己的题目；未联网时仍能答题。")
        val result = TextView(this).apply { style.text(this); setPadding(0, style.dp(6), 0, 0) }
        questions.addView(result)
        fun copyPrompt(rotate: Boolean) {
            result.text = "正在读取…"
            ReminderBankSync.connection(this, rotate) { prompt ->
                if (isFinishing || isDestroyed) return@connection
                if (prompt == null) result.text = "无法读取，请确认已登录并检查网络。"
                else {
                    val clip = android.content.ClipData.newPlainText("提醒题库接入", prompt)
                    if (Build.VERSION.SDK_INT >= 33) clip.description.extras = android.os.PersistableBundle().apply {
                        putBoolean(android.content.ClipDescription.EXTRA_IS_SENSITIVE, true)
                    }
                    getSystemService(android.content.ClipboardManager::class.java).setPrimaryClip(clip)
                    result.text = if (rotate) "已更换密钥并复制新 Prompt。" else "已复制接入 Prompt。"
                }
            }
        }
        button(questions, "复制题库接入 Prompt") { copyPrompt(false) }
        button(questions, "同步题库") {
            result.text = "正在同步…"
            ReminderBankSync.refresh(this) { count ->
                if (!isFinishing && !isDestroyed) result.text = count?.let { "已同步 $it 道自定义题。" } ?: "同步失败，保留本机题库。"
            }
        }
        button(questions, "更换维护密钥") {
            android.app.AlertDialog.Builder(this).setTitle("更换题库密钥")
                .setMessage("现有接入密钥将失效，需要更新 Agent 的配置。")
                .setNegativeButton("取消", null).setPositiveButton("更换") { _, _ -> copyPrompt(true) }.show()
        }
        val background = card("后台计时")
        permission(background, "后台电量策略", PermissionStatus.batteryUnrestricted(this), "保持锁屏后的专注、休息计时及约定提醒时间。") {
            val action = if (PermissionStatus.batteryUnrestricted(this)) Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS
                else Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS
            openSafely(Intent(action).apply {
                if (action == Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS) data = Uri.parse("package:$packageName")
            })
        }
        button(list, "返回计时", true) { finish() }
        val container = FrameLayout(this).apply {
            setBackgroundColor(android.graphics.Color.TRANSPARENT)
            addView(list, FrameLayout.LayoutParams(minOf(resources.displayMetrics.widthPixels, style.dp(680)), -2, Gravity.TOP or Gravity.CENTER_HORIZONTAL))
        }
        root = ScrollView(this).apply { isFillViewport = true; addView(container); setBackgroundColor(style.canvas) }
        setContentView(root)
        AppWindowLayout.apply(this, root)
        root.post { root.scrollTo(0, scroll) }
    }

    private fun threshold(minutes: Int) = if (minutes == 0) "不弹出" else "$minutes 分钟"

    private fun configureReminders() {
        val form = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(style.dp(18), 0, style.dp(18), 0) }
        fun field(title: String, value: String, input: Int) = EditText(this).apply {
            label(form, title)
            setSingleLine(true); inputType = input; setText(value); contentDescription = title
            form.addView(this, LinearLayout.LayoutParams(-1, -2))
        }
        val number = android.text.InputType.TYPE_CLASS_NUMBER
        val pause = field("连续暂停（0 关闭，或 6–120 分钟）", popup.pauseMinutes.toString(), number)
        val idle = field("结束后在开盘时段闲置（0 关闭，或 6–120 分钟）", popup.idleMinutes.toString(), number)
        val durations = field("三个静默时长（1–240 分钟，用逗号分隔）", popup.muteOptions.joinToString(","), android.text.InputType.TYPE_CLASS_TEXT)
        val dialog = android.app.AlertDialog.Builder(this).setTitle("提醒与静默时间").setView(ScrollView(this).apply { addView(form) })
            .setPositiveButton("保存", null).setNegativeButton("取消", null).create()
        dialog.setOnShowListener {
            dialog.getButton(android.app.AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                val pauseValue = pause.text.toString().trim().toIntOrNull()
                val idleValue = idle.text.toString().trim().toIntOrNull()
                val values = durations.text.toString().split(',', '，').map { it.trim().toIntOrNull() }
                when {
                    popup.pending.isNotBlank() -> { dialog.dismiss(); render() }
                    pauseValue == null || pauseValue != 0 && pauseValue !in 6..120 -> pause.error = "请输入 0 或 6–120"
                    idleValue == null || idleValue != 0 && idleValue !in 6..120 -> idle.error = "请输入 0 或 6–120"
                    values.size != 3 || values.distinct().size != 3 || values.any { it == null || it !in 1..240 } -> durations.error = "请输入三个不同的 1–240 分钟值"
                    else -> {
                        popup.pauseMinutes = pauseValue; popup.idleMinutes = idleValue; popup.muteOptions = values.filterNotNull()
                        FocusService.reminderSettingsChanged(this); dialog.dismiss(); render()
                    }
                }
            }
        }
        dialog.show()
    }

    private fun card(title: String): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(style.dp(14), style.dp(12), style.dp(14), style.dp(12))
        background = style.rounded()
        list.addView(this, LinearLayout.LayoutParams(-1, -2).apply { topMargin = style.dp(8) })
        label(this, title, 15f)
    }
    private fun label(parent: LinearLayout, value: String, size: Float = 12f) {
        parent.addView(TextView(this).apply {
            style.text(this, size); text = value; setLineSpacing(style.dp(3).toFloat(), 1f)
            setPadding(0, style.dp(4), 0, style.dp(6))
        })
    }
    private fun toggle(parent: LinearLayout, value: String, checked: Boolean, action: (Boolean) -> Unit) {
        parent.addView(Switch(this).apply {
            style.text(this); text = value; isChecked = checked; minHeight = style.dp(34)
            setOnCheckedChangeListener { _, enabled -> action(enabled) }
        }, LinearLayout.LayoutParams(-1, -2))
    }
    private fun button(parent: LinearLayout, title: String, primary: Boolean = false, action: () -> Unit) {
        parent.addView(Button(this).apply {
            text = title; style.button(this, primary); setOnClickListener { action() }
        }, LinearLayout.LayoutParams(-1, -2).apply { topMargin = style.dp(8) })
    }
    private fun permission(parent: LinearLayout, title: String, granted: Boolean, note: String, action: () -> Unit) {
        label(parent, "$title · ${if (granted) "已开启" else "待设置"}")
        label(parent, note, 11f)
        button(parent, if (granted) "检查$title" else "设置$title", action = action)
    }
    private fun openSafely(primary: Intent) {
        val fallback = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName"))
        runCatching { startActivity(if (primary.resolveActivity(packageManager) != null) primary else fallback) }
    }
    override fun onDestroy() { unbindBlur?.invoke(); unbindBlur = null; super.onDestroy() }
    override fun onPause() { FocusService.setAppVisible(this, false); super.onPause() }
}
