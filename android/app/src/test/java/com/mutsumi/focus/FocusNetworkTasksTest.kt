package com.mutsumi.focus

import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong

class FocusNetworkTasksTest {
    @Test fun `a blocked background request cannot delay a user action`() {
        val network = FocusNetworkTasks()
        val reading = CountDownLatch(1)
        val releaseRead = CountDownLatch(1)
        val actionFinished = CountDownLatch(1)
        try {
            network.synchronize { reading.countDown(); releaseRead.await() }
            assertTrue(reading.await(3, TimeUnit.SECONDS))
            network.act { actionFinished.countDown() }
            assertTrue("Action was queued behind the blocked poll", actionFinished.await(3, TimeUnit.SECONDS))
            assertEquals(1L, releaseRead.count)
        } finally { releaseRead.countDown(); network.close() }
    }

    @Test fun `a poll started before an action stays stale even after that action fails`() {
        val network = FocusNetworkTasks()
        val readStarted = CountDownLatch(1)
        val actionFinished = CountDownLatch(1)
        val generation = AtomicLong(-1)
        try {
            network.synchronize { generation.set(it); readStarted.countDown() }
            assertTrue(readStarted.await(3, TimeUnit.SECONDS))
            assertTrue(network.isCurrentSync(generation.get()))
            // No state transition or successful result is needed to fence out the old read.
            network.act { actionFinished.countDown() }
            assertTrue(actionFinished.await(3, TimeUnit.SECONDS))
            assertFalse(network.isCurrentSync(generation.get()))
        } finally { network.close() }
    }

    @Test fun `fresh polls can reconcile after an action`() {
        val network = FocusNetworkTasks()
        val actionFinished = CountDownLatch(1)
        val readFinished = CountDownLatch(1)
        val generation = AtomicLong(-1)
        try {
            network.act { actionFinished.countDown() }
            assertTrue(actionFinished.await(3, TimeUnit.SECONDS))
            network.synchronize { generation.set(it); readFinished.countDown() }
            assertTrue(readFinished.await(3, TimeUnit.SECONDS))
            assertTrue(network.isCurrentSync(generation.get()))
        } finally { network.close() }
    }

    @Test fun `service cleanup interrupts both active workers`() {
        val network = FocusNetworkTasks()
        val started = CountDownLatch(2)
        val stopped = CountDownLatch(2)
        val waitForCleanup = CountDownLatch(1)
        val task = {
            started.countDown()
            try { waitForCleanup.await() }
            catch (_: InterruptedException) { stopped.countDown() }
            Unit
        }
        try {
            network.synchronize { task() }
            network.act(task)
            assertTrue(started.await(3, TimeUnit.SECONDS))
            network.close()
            assertTrue("Network workers survived service cleanup", stopped.await(3, TimeUnit.SECONDS))
        } finally { waitForCleanup.countDown(); network.close() }
    }
}
