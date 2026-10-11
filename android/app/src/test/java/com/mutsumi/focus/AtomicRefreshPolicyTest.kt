package com.mutsumi.focus

import org.junit.Assert.*
import org.junit.Test

class AtomicRefreshPolicyTest {
    @Test fun `second ticks and rapid transitions coalesce into the latest ten second update`() {
        val policy = AtomicRefreshPolicy()
        assertTrue(policy.shouldPublish("focus", 0, true, true))
        policy.published("focus", 0)
        for (second in 1..9) assertFalse(policy.shouldPublish("pause:$second", second * 1000L, true, false))
        assertTrue(policy.shouldPublish("pause:10", 10_000, true, false))
        policy.published("pause:10", 10_000)
        assertFalse(policy.shouldPublish("pause:10", 30_000, true, false))
        assertTrue(policy.shouldPublish("focus:latest", 30_000, true, false))
    }

    @Test fun `failed publications do not consume a reminder update slot`() {
        val policy = AtomicRefreshPolicy()
        policy.published("paused", 1000)
        assertTrue(policy.shouldPublish("round1", 11_000, true, false))
        assertTrue(policy.shouldPublish("round1", 11_001, true, false))
        policy.published("round1", 11_001)
        assertFalse(policy.shouldPublish("round1", 30_000, true, false))
        assertTrue(policy.shouldPublish("round2", 311_001, true, false))
    }

    @Test fun `foreground start still discharges the accepted service request`() {
        val policy = AtomicRefreshPolicy()
        policy.published("previous", 1000)
        assertTrue(policy.shouldPublish("current", 1001, true, true))
    }
}
