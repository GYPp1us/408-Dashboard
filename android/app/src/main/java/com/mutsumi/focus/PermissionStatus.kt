package com.mutsumi.focus

import android.Manifest
import android.accessibilityservice.AccessibilityServiceInfo
import android.app.NotificationManager
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import android.view.accessibility.AccessibilityManager

object PermissionStatus {
    fun notifications(context: Context): Boolean {
        val runtimeGranted = Build.VERSION.SDK_INT < 33 ||
            context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
        return runtimeGranted && context.getSystemService(NotificationManager::class.java).areNotificationsEnabled()
    }

    fun overlay(context: Context): Boolean = Settings.canDrawOverlays(context)

    fun accessibility(context: Context): Boolean {
        val manager = context.getSystemService(AccessibilityManager::class.java)
        return manager.getEnabledAccessibilityServiceList(AccessibilityServiceInfo.FEEDBACK_ALL_MASK)
            .any { it.resolveInfo.serviceInfo.packageName == context.packageName && it.resolveInfo.serviceInfo.name.endsWith("FocusAccessibilityService") }
    }

    fun batteryUnrestricted(context: Context): Boolean =
        context.getSystemService(PowerManager::class.java).isIgnoringBatteryOptimizations(context.packageName)

    fun promotedNotifications(context: Context): Boolean =
        Build.VERSION.SDK_INT < 36 || context.getSystemService(NotificationManager::class.java).canPostPromotedNotifications()

    fun reminderOverlayAvailable(context: Context): Boolean = accessibility(context) || overlay(context)

    fun allRecommended(context: Context): Boolean =
        notifications(context) && overlay(context) && accessibility(context) &&
            batteryUnrestricted(context) && promotedNotifications(context)
}
