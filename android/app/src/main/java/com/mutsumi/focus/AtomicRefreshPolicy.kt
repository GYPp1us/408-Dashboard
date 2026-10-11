package com.mutsumi.focus

/** doc895: at most one refresh per ten seconds; rebuild only the latest state. */
class AtomicRefreshPolicy {
    private var lastPublishedAt = Long.MIN_VALUE
    private var lastSignature: String? = null

    fun shouldPublish(signature: String, nowElapsedMs: Long, atomic: Boolean, foregroundRequired: Boolean): Boolean {
        if (foregroundRequired || lastSignature == null) return true
        if (lastSignature == signature) return false
        val interval = if (atomic) 10_000L else 1_000L
        return nowElapsedMs - lastPublishedAt >= interval
    }

    fun published(signature: String, nowElapsedMs: Long) {
        lastSignature = signature
        lastPublishedAt = nowElapsedMs
    }
}
