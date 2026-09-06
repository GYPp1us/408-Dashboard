package com.mutsumi.focus

import android.app.Activity
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.webkit.CookieManager
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.FrameLayout
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import androidx.core.content.ContextCompat

class MainActivity : ComponentActivity() {
    private lateinit var webView: WebView
    private lateinit var permissionChip: Button
    private var receiverRegistered = false

    private val refreshReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            webView.evaluateJavascript("window.MutsumiWeb?.refresh?.()", null)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        CookieManager.getInstance().setAcceptCookie(true)
        setContentView(buildContent())
        configureWebView()
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (webView.canGoBack()) webView.goBack() else {
                    isEnabled = false
                    onBackPressedDispatcher.onBackPressed()
                }
            }
        })
        val restored = savedInstanceState != null && webView.restoreState(savedInstanceState) != null
        if (!restored) webView.loadUrl(restorableUrl(FocusStateStore(this).lastPageUrl()))
        val store = FocusStateStore(this)
        if (!store.onboardingSeen()) {
            store.setOnboardingSeen()
            openPermissionSetup()
        }
    }

    private fun buildContent(): View {
        val root = FrameLayout(this).apply { setBackgroundColor(Color.rgb(34, 28, 26)) }
        webView = WebView(this)
        root.addView(webView, FrameLayout.LayoutParams(-1, -1))
        permissionChip = Button(this).apply {
            text = "完善提醒权限"
            textSize = 8f
            setTextColor(Color.WHITE)
            setBackgroundColor(Color.rgb(185, 74, 67))
            setOnClickListener { openPermissionSetup() }
        }
        root.addView(permissionChip, FrameLayout.LayoutParams(-2, dp(26)).apply {
            gravity = Gravity.TOP or Gravity.END
            topMargin = dp(4)
            marginEnd = dp(4)
        })
        return root
    }

    @Suppress("SetJavaScriptEnabled")
    private fun configureWebView() {
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
            allowFileAccess = false
            allowContentAccess = false
            cacheMode = WebSettings.LOAD_CACHE_ELSE_NETWORK
            setSupportMultipleWindows(false)
            userAgentString = "$userAgentString MutsumiFocus/${BuildConfig.VERSION_NAME}"
        }
        webView.addJavascriptInterface(FocusBridge(this), "MutsumiAndroid")
        webView.webChromeClient = WebChromeClient()
        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val configured = Uri.parse(BuildConfig.DASHBOARD_URL)
                val target = request.url
                if (target.scheme == "https" && target.host == configured.host) return false
                startActivity(Intent(Intent.ACTION_VIEW, target))
                return true
            }

            override fun onPageFinished(view: WebView, url: String) {
                super.onPageFinished(view, url)
                if (isTrustedUrl(url)) FocusStateStore(this@MainActivity).setLastPageUrl(url)
            }
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        webView.saveState(outState)
        super.onSaveInstanceState(outState)
    }

    override fun onResume() {
        super.onResume()
        permissionChip.visibility = if (PermissionStatus.allRecommended(this)) View.GONE else View.VISIBLE
        if (FocusAccessibilityService.isConnected()) FocusService.requestReminderCheck(this)
    }

    override fun onStart() {
        super.onStart()
        if (!receiverRegistered) {
            val filter = IntentFilter(FocusService.ACTION_REFRESH_WEB)
            ContextCompat.registerReceiver(this, refreshReceiver, filter, ContextCompat.RECEIVER_NOT_EXPORTED)
            receiverRegistered = true
        }
    }

    override fun onStop() {
        if (receiverRegistered) {
            unregisterReceiver(refreshReceiver)
            receiverRegistered = false
        }
        super.onStop()
    }

    override fun onDestroy() {
        webView.removeJavascriptInterface("MutsumiAndroid")
        webView.destroy()
        super.onDestroy()
    }

    fun openPermissionSetup() {
        startActivity(Intent(this, PermissionSetupActivity::class.java))
    }

    private fun restorableUrl(candidate: String?): String =
        candidate?.takeIf(::isTrustedUrl) ?: BuildConfig.DASHBOARD_URL

    private fun isTrustedUrl(candidate: String): Boolean {
        val configured = Uri.parse(BuildConfig.DASHBOARD_URL)
        val target = Uri.parse(candidate)
        return target.scheme == "https" && target.host == configured.host
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()
}
