package com.mutsumi.focus

/** Renew a bounded CPU lease before expiry, independently of notification updates. */
object FocusRuntimeLease {
    const val TIMEOUT_MS = 10 * 60_000L
    const val RENEW_AFTER_MS = 8 * 60_000L
    const val STALLED_AFTER_MS = 60_000L

    fun needsRenewal(held: Boolean, acquiredAt: Long, now: Long): Boolean =
        !held || now - acquiredAt >= RENEW_AFTER_MS

    fun stalled(lastTick: Long?, now: Long): Boolean =
        lastTick != null && now - lastTick >= STALLED_AFTER_MS
}
