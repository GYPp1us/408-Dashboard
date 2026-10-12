package com.mutsumi.focus

/** User-requested one-second live snapshots; unchanged summaries do not refresh. */
class AtomicRefreshPolicy {
    private var lastPublishedAt = Long.MIN_VALUE
    private var lastSignature: String? = null

    fun shouldPublish(signature: String, nowElapsedMs: Long, foregroundRequired: Boolean): Boolean {
        if (foregroundRequired || lastSignature == null) return true
        if (lastSignature == signature) return false
        return nowElapsedMs - lastPublishedAt >= 1_000L
    }

    fun published(signature: String, nowElapsedMs: Long) {
        lastSignature = signature
        lastPublishedAt = nowElapsedMs
    }
}
