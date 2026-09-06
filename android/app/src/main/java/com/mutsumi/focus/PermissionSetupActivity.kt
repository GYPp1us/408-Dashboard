package com.mutsumi.focus

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

class PermissionSetupActivity : Activity() {
    private lateinit var list: LinearLayout

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        FocusStateStore(this).setOnboardingSeen()
        render()
    }

    override fun onResume() {
        super.onResume()
        if (::list.isInitialized) render()
    }

    private fun render() {
        list = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(12), dp(14), dp(12), dp(16))
            setBackgroundColor(Color.rgb(244, 238, 231))
        }
        list.addView(TextView(this).apply {
            text = "让提醒真正出现"
            textSize = 14f
            setTextColor(Color.rgb(34, 28, 26))
            setTypeface(typeface, Typeface.BOLD)
        })
        list.addView(TextView(this).apply {
            text = "权限仅用于后台计时、OriginOS 原子岛尝试与超时提醒。无厂商认证时自动降级为普通持续通知；无障碍只是悬浮层失败后的可选兜底。"
            textSize = 8f
            setTextColor(Color.rgb(74, 63, 58))
            setPadding(0, dp(6), 0, dp(9))
        })

        addPermission(
            "① 通知与实时状态",
            PermissionStatus.notifications(this),
            "允许持续计时、通知操作和原子岛降级展示。",
        ) {
            if (Build.VERSION.SDK_INT >= 33) requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 40)
            else openSafely(openAppDetailsIntent(), openAppDetailsIntent())
        }
        if (Build.VERSION.SDK_INT >= 36) {
            val promotionIntent = Intent(Settings.ACTION_APP_NOTIFICATION_PROMOTION_SETTINGS).apply {
                putExtra(Settings.EXTRA_APP_PACKAGE, packageName)
            }
            val available = promotionIntent.resolveActivity(packageManager) != null
            addPermission(
                "①-B Android 实时通知推广",
                PermissionStatus.promotedNotifications(this),
                "允许 Android 16 把持续计时显示为 Live Update；不影响普通通知兜底。",
                available = available,
                unavailableLabel = "系统无独立入口",
            ) {
                openSafely(promotionIntent, appNotificationSettings())
            }
        } else {
            addPermission(
                "①-B 实时通知展示",
                true,
                "当前系统没有 Android 16 独立推广权限页，实时形态由系统通知管理，无需单独开启。",
                available = false,
                unavailableLabel = "由系统管理",
            ) {}
        }
        addPermission(
            "② 显示在其他应用上层",
            PermissionStatus.overlay(this),
            "首选的全屏半透明提醒层，不依赖读取其他应用内容。",
        ) { openSafely(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName")), openAppDetailsIntent()) }
        addPermission(
            "③ 不限制后台电量",
            PermissionStatus.batteryUnrestricted(this),
            "避免 OriginOS 在计时或等待提醒时冻结服务。",
        ) { requestBatteryExemption() }
        addPermission(
            "④ 无障碍提醒层（可选）",
            PermissionStatus.accessibility(this),
            "仅在悬浮层不可用时绘制提醒；配置禁止读取窗口内容，不影响核心计时。",
        ) { openSafely(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS), openAppDetailsIntent()) }

        list.addView(Button(this).apply {
            text = "继续进入计时页面"
            textSize = 8f
            setTextColor(Color.WHITE)
            setBackgroundColor(Color.rgb(51, 41, 37))
            setOnClickListener {
                FocusStateStore(this@PermissionSetupActivity).setOnboardingSeen()
                finish()
            }
        }, LinearLayout.LayoutParams(-1, dp(28)).apply { topMargin = dp(9) })

        setContentView(ScrollView(this).apply { addView(list) })
    }

    private fun addPermission(
        title: String,
        granted: Boolean,
        explanation: String,
        available: Boolean = true,
        unavailableLabel: String = "不可用",
        action: () -> Unit,
    ) {
        val card = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(9), dp(8), dp(9), dp(8))
            setBackgroundColor(Color.WHITE)
        }
        card.addView(TextView(this).apply {
            text = "$title  ${if (!available) unavailableLabel else if (granted) "已开启" else "待开启"}"
            textSize = 8.5f
            setTypeface(typeface, Typeface.BOLD)
            setTextColor(if (granted || !available) Color.rgb(61, 112, 78) else Color.rgb(185, 74, 67))
        })
        card.addView(TextView(this).apply {
            text = explanation
            textSize = 7f
            setTextColor(Color.rgb(86, 75, 69))
            setPadding(0, dp(3), 0, dp(5))
        })
        card.addView(Button(this).apply {
            text = if (!available) unavailableLabel else if (granted) "检查设置" else "去开启"
            textSize = 8f
            isAllCaps = false
            isEnabled = available
            setOnClickListener { action() }
        }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, dp(32)).apply { gravity = Gravity.END })
        list.addView(card, LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dp(6) })
    }

    private fun requestBatteryExemption() {
        val power = getSystemService(PowerManager::class.java)
        val action = if (power.isIgnoringBatteryOptimizations(packageName)) {
            Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS
        } else {
            Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS
        }
        try {
            startActivity(Intent(action, Uri.parse("package:$packageName")))
        } catch (_: Exception) {
            openSafely(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS), openAppDetailsIntent())
        }
    }

    private fun appNotificationSettings(): Intent = Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
        .putExtra(Settings.EXTRA_APP_PACKAGE, packageName)

    private fun openAppDetailsIntent(): Intent =
        Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName"))

    private fun openSafely(primary: Intent, fallback: Intent) {
        val target = if (primary.resolveActivity(packageManager) != null) primary else fallback
        try { startActivity(target) }
        catch (_: Exception) { startActivity(openAppDetailsIntent()) }
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()
}
