package com.mutsumi.focus

import android.app.Activity
import android.app.AlertDialog
import android.app.NotificationManager
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.os.Build
import android.os.Bundle
import android.os.Process
import android.provider.Settings
import android.text.InputFilter
import android.text.InputType
import android.util.Log
import android.view.View
import android.view.inputmethod.InputMethodManager
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import com.mutsumi.focus.localadb.AtomicSceneRegistration
import com.mutsumi.focus.localadb.LocalAdbClient
import java.io.File
import java.util.concurrent.Executors

class AtomicIslandSetupActivity : Activity() {
    private lateinit var root: ScrollView
    private lateinit var content: LinearLayout
    private lateinit var sectionContent: LinearLayout
    private lateinit var style: SetupStyle
    private lateinit var status: TextView
    private lateinit var pairingResult: TextView
    private lateinit var registrationResult: TextView
    private lateinit var pairingPort: EditText
    private lateinit var pairingCode: EditText
    private lateinit var connectionPort: EditText
    private val actions = mutableListOf<Button>()
    private val worker = Executors.newSingleThreadExecutor()
    @Volatile private var client: LocalAdbClient? = null
    private var busy = false
    private val supported get() = Build.VERSION.SDK_INT >= 30 && AtomicSceneRegistration.isSupported(Build.MODEL, Build.DISPLAY)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        style = SetupStyle(this)
        content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(18), dp(20), dp(24))
            setBackgroundColor(style.paper)
        }
        sectionContent = content
        label("启用原子岛", 24f, true)
        label("仅在这台手机上完成配对和启用。成功后可以关闭无线调试，日常计时不需要电脑。")
        status = label("正在检查…", 16f, true)
        label("${Build.MODEL} · ${Build.DISPLAY}", 12f)
        if (!supported) label("当前系统尚未适配注册流程。系统升级后需重新验证，已开启的计时仍可使用。", 14f)

        section("1 · 打开无线调试")
        label("连接 Wi-Fi，先把 Mutsumi Focus 切换为小窗。然后点下方按钮，独立打开开发者选项，将系统设置保持全屏，在里面开启「无线调试」。")
        button("独立打开开发者选项", guarded = false) { openDeveloperSettings() }

        section("2 · 与当前手机配对")
        label("在全屏系统设置中点「使用配对码配对设备」，让配对弹窗始终可见。从 Mutsumi 小窗输入弹窗地址冒号后的配对端口和六位码，点下方按钮。设置配对页退到后台会中断配对。")
        pairingPort = numberInput("配对端口，例如 37123", 5)
        pairingCode = numberInput("六位配对码", 6, secret = true)
        button("完成本机配对") {
            val port = readPort(pairingPort) ?: return@button
            val code = pairingCode.text.toString().trim()
            if (!code.matches(Regex("[0-9]{6}"))) { pairingCode.error = "请输入六位配对码"; return@button }
            pairingCode.text.clear()
            operate("正在配对，请保持系统配对弹窗打开…", pairing = true) { adb ->
                adb.pair(port, code)
                "配对成功。回到无线调试主页，填写主页显示的连接端口，再启用原子岛。"
            }
        }
        pairingResult = label("本次配对：等待操作。", 14f)

        section("3 · 注册专注场景")
        label("填写无线调试主页「IP 地址与端口」中的端口。它与上一步的配对端口不同，每次开启无线调试可能变化。")
        connectionPort = numberInput("连接端口，例如 39841", 5)
        button("连接并启用原子岛") { configure(true) }
        registrationResult = label("本次注册：等待操作。", 14f)
        label("配对码不会保存或上传；配对凭据仅存于应用私有目录。", 12f)

        section("完成与撤销")
        label("显示「已开启」后，返回计时页面开始专注。启用会保留其他应用的场景；撤销只移除本应用的专注场景。需要再次修改时，重新开启无线调试并填写当前连接端口。")
        button("撤销本应用的原子岛注册") { configure(false) }
        button("刷新授权状态", guarded = false) { refreshStatus() }
        label("若要取消调试授权，请在系统无线调试的已配对设备中，忘记「Mutsumi-Focus-local」。这与撤销原子岛注册是两个独立操作。", 12f)
        button("开源许可", guarded = false) { showLicenses() }
        button("返回计时页面", guarded = false) { finish() }

        pairingPort.setText(savedInstanceState?.getString("pairingPort").orEmpty())
        connectionPort.setText(savedInstanceState?.getString("connectionPort").orEmpty())
        val centered = android.widget.FrameLayout(this).apply {
            setBackgroundColor(style.paper)
            addView(content, android.widget.FrameLayout.LayoutParams(
                minOf(resources.displayMetrics.widthPixels, dp(680)), -2, android.view.Gravity.TOP or android.view.Gravity.CENTER_HORIZONTAL))
        }
        root = ScrollView(this).apply { isFillViewport = true; addView(centered) }
        setContentView(root)
        AppWindowLayout.apply(this, root)
        refreshStatus()
    }

    override fun onResume() {
        super.onResume()
        if (::status.isInitialized) refreshStatus()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        outState.putString("pairingPort", pairingPort.text.toString())
        outState.putString("connectionPort", connectionPort.text.toString())
        super.onSaveInstanceState(outState)
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus && ::root.isInitialized) AppWindowLayout.apply(this, root)
    }

    override fun onDestroy() {
        client?.close()
        worker.shutdownNow()
        super.onDestroy()
    }

    private fun configure(enabled: Boolean) {
        val port = readPort(connectionPort) ?: return
        operate(if (enabled) "正在连接、备份并注册…" else "正在撤销本应用的场景…", pairing = false) { adb ->
            val registration = AtomicSceneRegistration(packageName, Process.myUid() / 100_000)
            val change = adb.register(port, registration, enabled) { before ->
                File(noBackupFilesDir, "atomic-scene-before.txt").writeText(before)
            }
            File(noBackupFilesDir, "atomic-scene-after.txt").writeText(change.after)
            if (change.enabled) "已开启，系统授权回读通过。可以关闭无线调试并返回计时页面。"
            else "已撤销本应用的原子岛注册，其他应用的场景已核对保留。"
        }
    }

    private fun operate(progress: String, pairing: Boolean, operation: (LocalAdbClient) -> String) {
        if (busy || !supported) return
        busy = true
        actions.forEach { it.isEnabled = false }
        val output = if (pairing) pairingResult else registrationResult
        output.text = progress
        output.setTextColor(Color.rgb(54, 44, 38))
        getSystemService(InputMethodManager::class.java).hideSoftInputFromWindow(root.windowToken, 0)
        root.post { root.smoothScrollTo(0, output.top) }
        worker.execute {
            val adb = LocalAdbClient(this)
            client = adb
            try {
                check(!isDestroyed) { "操作已取消" }
                val message = operation(adb)
                showResult(message, output, success = true)
            } catch (error: Exception) {
                // Types only: pairing codes, private keys and exception messages are not logged.
                Log.w("MutsumiAtomicSetup", "pairing=$pairing failure=${error.javaClass.simpleName} cause=${error.cause?.javaClass?.simpleName}")
                val message = if (pairing) "配对失败。请保持配对弹窗打开，重新核对配对端口与配对码；已关闭的弹窗需要重新生成。"
                else if (error is IllegalStateException || error is IllegalArgumentException) error.message.orEmpty()
                else "连接失败或超时。请确认无线调试已开启、配对仍有效，并使用主页的连接端口。"
                showResult(message, output, success = false)
            } finally {
                adb.close()
                client = null
                runOnUiThread {
                    if (!isDestroyed) {
                        busy = false
                        actions.forEach { it.isEnabled = supported }
                        refreshStatus()
                    }
                }
            }
        }
    }

    private fun showResult(message: String, output: TextView, success: Boolean) = runOnUiThread {
        if (!isDestroyed) {
            output.text = message
            output.setTextColor(if (success) Color.rgb(61, 112, 78) else Color.rgb(185, 74, 67))
            root.post { root.smoothScrollTo(0, output.top) }
        }
    }

    private fun refreshStatus() {
        val enabled = runCatching {
            val manager = getSystemService(NotificationManager::class.java)
            manager.javaClass.getMethod("getSceneStatus", String::class.java, String::class.java)
                .invoke(manager, packageName, AtomicSceneRegistration.SCENE) as Boolean
        }.getOrNull()
        status.text = when (enabled) {
            true -> "系统已有场景授权 · 已开启"
            false -> "系统已有场景授权 · 未开启"
            null -> "系统场景授权 · 暂无法读取"
        }
        status.setTextColor(if (enabled == true) Color.rgb(61, 112, 78) else Color.rgb(185, 74, 67))
    }

    private fun openDeveloperSettings() {
        // Settings must have its own task: otherwise switching to our pairing
        // form stops the Settings pairing page inside this application's task.
        val developer = Intent(Settings.ACTION_APPLICATION_DEVELOPMENT_SETTINGS)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        val fallback = Intent(Settings.ACTION_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        try { startActivity(if (developer.resolveActivity(packageManager) != null) developer else fallback) }
        catch (_: Exception) { startActivity(fallback) }
    }

    private fun showLicenses() {
        val text = listOf("NOTICES.txt", "APACHE-2.0.txt", "SPAKE2-GPL-3.0.txt", "BC-LICENSE.txt")
            .joinToString("\n\n") { name -> assets.open("local-adb-licenses/$name").bufferedReader().use { it.readText() } }
        val body = TextView(this).apply { this.text = text; textSize = 12f; setPadding(dp(16), dp(12), dp(16), dp(12)) }
        AlertDialog.Builder(this).setTitle("开源许可").setView(ScrollView(this).apply { addView(body) })
            .setPositiveButton("关闭", null).show()
    }

    private fun readPort(field: EditText): Int? {
        val port = field.text.toString().trim().toIntOrNull()
        if (port == null || port !in 1..65535) { field.error = "请输入有效端口（1–65535）"; return null }
        return port
    }

    private fun label(value: String, size: Float = 14f, bold: Boolean = false): TextView = TextView(this).apply {
        text = value
        textSize = size
        style.text(this, size)
        if (bold) setTypeface(typeface, Typeface.BOLD)
        setPadding(0, dp(6), 0, dp(6))
        sectionContent.addView(this)
    }

    private fun section(value: String) {
        sectionContent = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(12), dp(16), dp(16))
            background = style.rounded()
            content.addView(this, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(18) })
        }
        label(value, 20f, true)
    }

    private fun numberInput(hintText: String, maxLength: Int, secret: Boolean = false): EditText = EditText(this).apply {
        hint = hintText
        textSize = 16f
        setTextColor(style.ink)
        setHintTextColor(style.muted)
        minHeight = dp(52)
        inputType = InputType.TYPE_CLASS_NUMBER or if (secret) InputType.TYPE_NUMBER_VARIATION_PASSWORD else 0
        filters = arrayOf(InputFilter.LengthFilter(maxLength))
        isSingleLine = true
        isSaveEnabled = false
        importantForAutofill = View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS
        sectionContent.addView(this, LinearLayout.LayoutParams(-1, -2))
    }

    private fun button(value: String, guarded: Boolean = true, action: () -> Unit) {
        val button = Button(this).apply {
            text = value
            textSize = 14f
            style.button(this)
            isAllCaps = false
            isEnabled = !guarded || supported
            setOnClickListener { action() }
        }
        if (guarded) actions += button
        sectionContent.addView(button, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(8) })
    }

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
}
