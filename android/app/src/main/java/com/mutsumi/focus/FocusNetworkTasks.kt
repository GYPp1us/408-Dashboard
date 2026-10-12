package com.mutsumi.focus

import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicLong

/** A slow background read must neither queue user actions nor overwrite their result. */
class FocusNetworkTasks : AutoCloseable {
    private val synchronization = Executors.newSingleThreadExecutor()
    private val actions = Executors.newSingleThreadExecutor()
    private val actionGeneration = AtomicLong()

    fun synchronize(task: (Long) -> Unit) {
        val generation = actionGeneration.get()
        synchronization.execute { task(generation) }
    }

    fun act(task: () -> Unit) {
        actionGeneration.incrementAndGet()
        actions.execute(task)
    }

    fun isCurrentSync(generation: Long): Boolean = generation == actionGeneration.get()

    override fun close() {
        synchronization.shutdownNow()
        actions.shutdownNow()
    }
}
