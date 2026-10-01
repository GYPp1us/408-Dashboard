package com.mutsumi.focus

import android.app.Activity
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.res.Configuration
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.SystemClock
import android.util.Log
import android.view.Gravity
import android.view.KeyEvent
import android.view.View
import android.webkit.CookieManager
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.FrameLayout
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat

class MainActivity : ComponentActivity() {
    private lateinit var webView: WebView
    private lateinit var permissionChip: Button
    private lateinit var contentRoot: FrameLayout
    private var receiverRegistered = false
    private var backInFlight = false
    private var cacheFallbackUrl: String? = null
    private var cacheFallbackPending = false
    private var fileChooserCallback: ValueCallback<Array<Uri>>? = null
    private var fileChooserPage: String? = null
    @Volatile private var fileChooserInFlight = false
    @Volatile private var fileChooserReturnedAt = 0L
    @Volatile private var systemOrientation = Configuration.ORIENTATION_UNDEFINED
    private val imageChooser = registerForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        fileChooserReturnedAt = SystemClock.uptimeMillis()
        if (BuildConfig.DEBUG) Log.d("MutsumiPicker", "result cancelled=${uri == null}")
        fileChooserInFlight = false
        val samePage = !isFinishing && !isDestroyed && ::webView.isInitialized &&
            webView.url == fileChooserPage && webView.url?.let(::isTrustedUrl) == true
        val image = if (samePage) readableImage(uri) else null
        completeFileChooser(image?.let { arrayOf(it) })
    }

    private val refreshReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            refreshTrustedDocument()
        }
    }

    private fun refreshTrustedDocument() {
        if (!hasTrustedDocument()) return
        webView.post {
            if (hasTrustedDocument()) webView.evaluateJavascript("window.MutsumiWeb?.refresh?.()", null)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // A restored picker result belongs to the destroyed WebView. Reject
        // another launch until that old result is delivered and discarded.
        fileChooserInFlight = savedInstanceState?.getBoolean("imageChooserInFlight") == true
        CookieManager.getInstance().setAcceptCookie(true)
        setContentView(buildContent())
        configureWebView()
        updateWindowLayout()
        FocusService.acknowledgeFromNotification(this, intent)
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (BuildConfig.DEBUG) Log.d("MutsumiPicker", "back pending=$fileChooserInFlight sinceResult=${SystemClock.uptimeMillis() - fileChooserReturnedAt}")
                // The system picker owns its cancellation gesture. A trailing
                // Back delivered as it returns must not also close the drawer.
                if (fileChooserInFlight || SystemClock.uptimeMillis() - fileChooserReturnedAt < 300) return
                if (backInFlight) return
                backInFlight = true
                // A modal owns Back before the document's navigation history.
                webView.evaluateJavascript("""(() => {
                    const dialogs = [...document.querySelectorAll('dialog[open]')];
                    const dialog = dialogs[dialogs.length - 1];
                    if (!dialog) return false;
                    const event = new Event('cancel', {cancelable: true});
                    dialog.dispatchEvent(event);
                    if (!event.defaultPrevented) dialog.close();
                    return true;
                })()""") { handled ->
                    backInFlight = false
                    if (!isFinishing && !isDestroyed && handled != "true") {
                        if (webView.canGoBack()) webView.goBack() else {
                            isEnabled = false
                            onBackPressedDispatcher.onBackPressed()
                        }
                    }
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
        contentRoot = root
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
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG)
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            setSupportZoom(false)
            builtInZoomControls = false
            displayZoomControls = false
            textZoom = 100
            useWideViewPort = true
            loadWithOverviewMode = false
            mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
            allowFileAccess = false
            allowContentAccess = false
            cacheMode = WebSettings.LOAD_DEFAULT
            setSupportMultipleWindows(false)
            userAgentString = "$userAgentString MutsumiFocus/${BuildConfig.VERSION_NAME}"
        }
        webView.addJavascriptInterface(FocusBridge(this), "MutsumiAndroid")
        webView.setOnKeyListener { _, key, event ->
            key == KeyEvent.KEYCODE_BACK && (fileChooserInFlight || event.downTime <= fileChooserReturnedAt ||
                SystemClock.uptimeMillis() - fileChooserReturnedAt < 300)
        }
        webView.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(
                view: WebView,
                callback: ValueCallback<Array<Uri>>,
                params: FileChooserParams,
            ): Boolean {
                if (callback === fileChooserCallback) return true
                val acceptTypes = params.acceptTypes.filter { it.isNotBlank() }
                val imagesOnly = acceptTypes.isNotEmpty() && acceptTypes.all {
                    it.trim().startsWith("image/", ignoreCase = true)
                }
                if (view !== webView || view.url?.let(::isTrustedUrl) != true ||
                    isFinishing || isDestroyed || fileChooserInFlight ||
                    params.mode != FileChooserParams.MODE_OPEN || !imagesOnly
                ) {
                    // We own cancellation, including repeated requests while
                    // the existing system picker still has an outstanding result.
                    deliverFileChoice(callback, null)
                    return true
                }
                fileChooserCallback = callback
                fileChooserPage = view.url
                fileChooserInFlight = true
                try {
                    imageChooser.launch("image/*")
                } catch (_: RuntimeException) {
                    fileChooserInFlight = false
                    completeFileChooser(null)
                }
                return true
            }
        }
        webView.webViewClient = object : WebViewClient() {
            override fun onPageStarted(view: WebView, url: String?, favicon: android.graphics.Bitmap?) {
                // Retry cache at most once per navigation, including a second
                // offline visit to the same route after reconnection.
                if (cacheFallbackPending && url == cacheFallbackUrl) {
                    cacheFallbackPending = false
                } else {
                    cacheFallbackUrl = null
                    cacheFallbackPending = false
                    view.settings.cacheMode = WebSettings.LOAD_DEFAULT
                }
                // Never deliver a selected file into a newly navigated document.
                completeFileChooser(null)
                super.onPageStarted(view, url, favicon)
            }

            override fun onReceivedError(view: WebView, request: WebResourceRequest, error: android.webkit.WebResourceError) {
                super.onReceivedError(view, request, error)
                val url = request.url.toString()
                val offlineError = error.errorCode in setOf(ERROR_HOST_LOOKUP, ERROR_CONNECT, ERROR_TIMEOUT, ERROR_IO)
                if (request.isForMainFrame && offlineError && isTrustedUrl(url) && cacheFallbackUrl != url) {
                    cacheFallbackUrl = url
                    cacheFallbackPending = true
                    view.settings.cacheMode = WebSettings.LOAD_CACHE_ELSE_NETWORK
                    view.loadUrl(url)
                }
            }

            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val target = request.url
                if (isTrustedUrl(target.toString())) return false
                try { startActivity(Intent(Intent.ACTION_VIEW, target)) }
                catch (_: android.content.ActivityNotFoundException) { /* No handler for this external route. */ }
                return true
            }

            override fun doUpdateVisitedHistory(view: WebView, url: String?, isReload: Boolean) {
                super.doUpdateVisitedHistory(view, url, isReload)
                if (url != null && isTrustedUrl(url)) FocusStateStore(this@MainActivity).setLastPageUrl(url)
            }

            override fun onPageFinished(view: WebView, url: String) {
                super.onPageFinished(view, url)
                if (!cacheFallbackPending) view.settings.cacheMode = WebSettings.LOAD_DEFAULT
                if (isTrustedUrl(url)) {
                    FocusStateStore(this@MainActivity).setLastPageUrl(url)
                    if (Uri.parse(url).path in setOf("/login", "/register")) {
                        FocusService.clear(this@MainActivity)
                    }
                }
            }
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        outState.putBoolean("imageChooserInFlight", fileChooserInFlight)
        webView.saveState(outState)
        super.onSaveInstanceState(outState)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        FocusService.acknowledgeFromNotification(this, intent)
    }

    override fun onResume() {
        super.onResume()
        updateWindowLayout()
        FocusService.requestReminderCheck(this)
        // A notification can change focus while this Activity's receiver is
        // stopped. Reconcile the retained document as soon as it returns.
        refreshTrustedDocument()
    }

    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        updateWindowLayout()
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus && ::contentRoot.isInitialized) {
            updateWindowLayout()
            refreshTrustedDocument()
        }
    }

    private fun updateWindowLayout() {
        systemOrientation = resources.configuration.orientation
        val landscape = AppWindowLayout.apply(this, contentRoot)
        permissionChip.visibility = if (landscape || PermissionStatus.allRecommended(this)) View.GONE else View.VISIBLE
        // Reserve a native strip while setup is incomplete. A floating chip
        // over the WebView would intercept its top-right Settings link.
        (webView.layoutParams as FrameLayout.LayoutParams).let { params ->
            val margin = if (permissionChip.visibility == View.VISIBLE) dp(34) else 0
            if (params.topMargin != margin) {
                params.topMargin = margin
                webView.layoutParams = params
            }
        }
        ViewCompat.requestApplyInsets(contentRoot)
        if (hasTrustedDocument()) webView.post {
            if (hasTrustedDocument()) webView.evaluateJavascript("window.MutsumiViewport?.update?.()", null)
        }
    }

    internal fun getDisplayOrientation(): String = when (systemOrientation) {
        Configuration.ORIENTATION_LANDSCAPE -> "landscape"
        Configuration.ORIENTATION_PORTRAIT -> "portrait"
        else -> "unknown"
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
        completeFileChooser(null)
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
        return target.scheme == "https" && target.host == configured.host && target.port == configured.port
    }

    internal fun hasTrustedDocument(): Boolean =
        !isFinishing && !isDestroyed && ::webView.isInitialized &&
            webView.url?.let(::isTrustedUrl) == true

    internal fun imagePickerOwnsBack(): Boolean =
        fileChooserInFlight || SystemClock.uptimeMillis() - fileChooserReturnedAt < 750

    private fun readableImage(uri: Uri?): Uri? {
        if (uri?.scheme != "content" || uri.authority.isNullOrBlank()) return null
        // No arbitrary file:// access or app-private provider URIs from an
        // untrusted picker. Backend validation remains authoritative for bytes.
        if (uri.authority == packageName || uri.authority!!.startsWith("$packageName.")) return null
        return try {
            if (contentResolver.getType(uri)?.startsWith("image/", ignoreCase = true) != true) return null
            contentResolver.openAssetFileDescriptor(uri, "r")?.use { uri }
        } catch (_: java.io.IOException) {
            null
        } catch (_: RuntimeException) {
            null
        }
    }

    private fun completeFileChooser(uris: Array<Uri>?) {
        val callback = fileChooserCallback
        // Clear ownership before invoking WebView: callbacks can re-enter.
        fileChooserCallback = null
        fileChooserPage = null
        if (callback != null) deliverFileChoice(callback, uris)
    }

    private fun deliverFileChoice(callback: ValueCallback<Array<Uri>>, uris: Array<Uri>?) {
        try { callback.onReceiveValue(uris) } catch (_: RuntimeException) {
            // An already destroyed renderer must not crash the Activity.
        }
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()
}
