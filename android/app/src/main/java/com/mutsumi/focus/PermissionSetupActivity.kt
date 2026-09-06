package com.mutsumi.focus

import android.Manifest
import android.app.Activity
import android.content.ComponentName
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
        render()
    }

    override fun onResume() {
        super.onResume()
        if (::list.isInitialized) render()
    }

    private fun render() {
        list = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(24), dp(28), dp(24), dp(32))
            setBackgroundColor(Color.rgb(244, 238, 231))
        }
        list.addView(TextView(this).apply {
            text = "让提醒真正出现"
            textSize = 28f
            setTextColor(Color.rgb(34, 28, 26))
            setTypeface(typeface, Typeface.BOLD)
        })
        list.addView(TextView(this).apply {
            text = "本应用不会读取屏幕或代替你操作。以下权限只用于维持计时、尝试 OriginOS 原子岛，以及在暂停 5 分钟或停止 15/30/60 分钟后显示遮罩。厂商场景权限未认证时会自动降级为普通持续通知。"
            textSize = 16f
            setTextColor(Color.rgb(74, 63, 58))
            setPadding(0, dp(12), 0, dp(18))
        })

        addPermission(
            "① 通知与实时状态",
            PermissionStatus.notifications(this),
            "允许持续计时、通知操作和原子岛降级展示。",
        ) {
            if (Build.VERSION.SDK_INT >= 33) requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 40)
            else openAppDetails()
        }
        if (Build.VERSION.SDK_INT >= 36) {
            addPermission(
                "①-B Android 实时通知推广",
                PermissionStatus.promotedNotifications(this),
                "允许 Android 16 把持续计时显示为 Live Update；不影响普通通知兜底。",
            ) {
                startActivity(Intent(Settings.ACTION_APP_NOTIFICATION_PROMOTION_SETTINGS).apply {
                    putExtra(Settings.EXTRA_APP_PACKAGE, packageName)
                })
            }
        }
        addPermission(
            "② 无障碍提醒层",
            PermissionStatus.accessibility(this),
            "仅绘制超时提醒层；配置明确禁止读取窗口内容。",
        ) { startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)) }
        addPermission(
            "③ 显示在其他应用上层",
            PermissionStatus.overlay(this),
            "无障碍服务不可用时的备用全屏半透明遮罩。",
        ) { startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName"))) }
        addPermission(
            "④ 不限制后台电量",
            PermissionStatus.batteryUnrestricted(this),
            "避免 OriginOS 在计时或等待提醒时冻结服务。",
        ) { requestBatteryExemption() }
        addPermission(
            "⑤ OriginOS 自启动",
            false,
            "打开 vivo 后台管理；请允许自启动和高耗电后台运行。此项无法由应用自动核验。",
        ) { openVivoBackgroundSettings() }

        list.addView(Button(this).apply {
            text = "继续进入计时页面"
            textSize = 16f
            setTextColor(Color.WHITE)
            setBackgroundColor(Color.rgb(51, 41, 37))
            setOnClickListener {
                FocusStateStore(this@PermissionSetupActivity).setOnboardingSeen()
                finish()
            }
        }, LinearLayout.LayoutParams(-1, dp(54)).apply { topMargin = dp(18) })

        setContentView(ScrollView(this).apply { addView(list) })
    }

    private fun addPermission(title: String, granted: Boolean, explanation: String, action: () -> Unit) {
        val card = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(18), dp(16), dp(18), dp(16))
            setBackgroundColor(Color.WHITE)
        }
        card.addView(TextView(this).apply {
            text = "$title  ${if (granted) "已开启" else "待开启"}"
            textSize = 17f
            setTypeface(typeface, Typeface.BOLD)
            setTextColor(if (granted) Color.rgb(61, 112, 78) else Color.rgb(185, 74, 67))
        })
        card.addView(TextView(this).apply {
            text = explanation
            textSize = 14f
            setTextColor(Color.rgb(86, 75, 69))
            setPadding(0, dp(6), 0, dp(10))
        })
        card.addView(Button(this).apply {
            text = if (granted) "检查设置" else "去开启"
            isAllCaps = false
            setOnClickListener { action() }
        }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, dp(44)).apply { gravity = Gravity.END })
        list.addView(card, LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dp(12) })
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
            startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
        }
    }

    private fun openVivoBackgroundSettings() {
        val candidates = listOf(
            ComponentName("com.vivo.permissionmanager", "com.vivo.permissionmanager.activity.BgStartUpManagerActivity"),
            ComponentName("com.iqoo.secure", "com.iqoo.secure.ui.phoneoptimize.AddWhiteListActivity"),
        )
        for (component in candidates) {
            try {
                startActivity(Intent().setComponent(component))
                return
            } catch (_: Exception) {
                // Different OriginOS releases expose different settings components.
            }
        }
        openAppDetails()
    }

    private fun openAppDetails() {
        startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName")))
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()
}
