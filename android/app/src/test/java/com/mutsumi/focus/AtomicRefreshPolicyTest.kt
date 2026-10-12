package com.mutsumi.focus

import org.junit.Assert.*
import org.junit.Test

class AtomicRefreshPolicyTest {
    @Test fun `live snapshots refresh every second without replaying queued states`() {
        val policy = AtomicRefreshPolicy()
        assertTrue(policy.shouldPublish("focus:0", 0, true))
        policy.published("focus:0", 0)
        assertFalse(policy.shouldPublish("pause:0", 999, false))
        for (second in 1..12) {
            assertTrue(policy.shouldPublish("focus:$second", second * 1000L, false))
            policy.published("focus:$second", second * 1000L)
        }
        assertFalse(policy.shouldPublish("focus:12", 99_000, false))
        assertTrue(policy.shouldPublish("pause:latest", 99_000, false))
    }

    @Test fun `failed publications do not consume a reminder update slot`() {
        val policy = AtomicRefreshPolicy()
        policy.published("paused", 1000)
        assertTrue(policy.shouldPublish("round1", 2000, false))
        assertTrue(policy.shouldPublish("round1", 2001, false))
        policy.published("round1", 2001)
        assertFalse(policy.shouldPublish("round1", 30_000, false))
        assertTrue(policy.shouldPublish("round2", 302_001, false))
    }

    @Test fun `foreground start still discharges the accepted service request`() {
        val policy = AtomicRefreshPolicy()
        policy.published("previous", 1000)
        assertTrue(policy.shouldPublish("current", 1001, true))
    }
}
