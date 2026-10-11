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

class PermissionSetupActivity : Activity() {
    private lateinit var style: SetupStyle
    private lateinit var list: LinearLayout
    private lateinit var root: ScrollView
    private lateinit var store: FocusStateStore
    private var unbindBlur: (() -> Unit)? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        store = FocusStateStore(this)
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
        val reminders = card("提醒方式")
        label(reminders, "温和提醒（默认）\n前台在专注卡片内提示，后台通过原子岛和通知提示。查看提醒不会恢复计时。")
        toggle(reminders, "强提醒 · 全屏毛玻璃覆盖层", store.strongReminders()) {
            store.setStrongReminders(it)
            FocusService.requestReminderCheck(this)
            render()
        }
        label(reminders, "强提醒会覆盖当前应用，需要你主动开启相应权限。关闭后立即恢复温和提醒。")
        if (store.strongReminders()) {
            permission(reminders, "显示在其他应用上层", PermissionStatus.overlay(this), "仅用于你选择的强提醒。") {
                openSafely(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName")))
            }
            permission(reminders, "无障碍覆盖层（可选）", PermissionStatus.accessibility(this), "悬浮层不可用时的备用方式，不读取窗口内容。") {
                openSafely(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
            }
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
    override fun onStop() { FocusService.setAppVisible(this, false); super.onStop() }
}
