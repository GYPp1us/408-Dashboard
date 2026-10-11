package com.mutsumi.focus.localadb

import android.content.Context
import android.util.AtomicFile
import com.flyfishxu.kadb.Kadb
import com.flyfishxu.kadb.cert.KadbCert
import kotlinx.coroutines.runBlocking
import java.io.DataInputStream
import java.io.DataOutputStream
import java.io.File
import java.io.IOException
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/** One operation, one loopback-only transport. No desktop ADB server is involved. */
internal class LocalAdbClient(context: Context) : AutoCloseable {
    private val credentials = AtomicFile(File(context.noBackupFilesDir, "atomic-adb-credentials"))
    private val closed = AtomicBoolean(false)
    @Volatile private var bridge: LoopbackBridge? = null
    @Volatile private var connection: Kadb? = null

    fun pair(port: Int, code: String) {
        require(code.matches(Regex("[0-9]{6}"))) { "请输入六位配对码" }
        prepareCredentials()
        withBridge(port) { relay ->
            runBlocking { Kadb.pair("127.0.0.1", relay.port, code, "Mutsumi-Focus-local") }
        }
    }

    fun register(port: Int, registration: AtomicSceneRegistration, enabled: Boolean, saveBefore: (String) -> Unit): AtomicSceneRegistration.Result {
        prepareCredentials()
        return withBridge(port) { relay ->
            val adb = Kadb.create("127.0.0.1", relay.port, connectTimeout = 4_000, socketTimeout = 12_000)
            connection = adb
            try {
                registration.configure(AtomicSceneRegistration.Shell { command ->
                    check(!closed.get()) { "操作已取消" }
                    val response = adb.shell(command)
                    check(response.exitCode == 0 && response.errorOutput.isBlank()) { "本机调试命令执行失败" }
                    response.output
                }, enabled, saveBefore)
            } finally {
                adb.close()
                connection = null
            }
        }
    }

    private fun <T> withBridge(remotePort: Int, action: (LoopbackBridge) -> T): T {
        require(remotePort in 1..65535) { "端口需要在 1–65535 之间" }
        check(!closed.get()) { "操作已取消" }
        val relay = LoopbackBridge(remotePort)
        bridge = relay
        return try {
            check(!closed.get()) { "操作已取消" }
            action(relay)
        } finally {
            relay.close()
            bridge = null
        }
    }

    private fun prepareCredentials() = synchronized(CREDENTIAL_LOCK) {
        if (credentials.baseFile.exists()) {
            DataInputStream(credentials.openRead()).use { stream ->
                fun readPart(): ByteArray {
                    val length = stream.readInt()
                    check(length in 1..16_384) { "本机配对凭据损坏" }
                    return ByteArray(length).also { stream.readFully(it) }
                }
                val certificate = readPart()
                val key = readPart()
                check(stream.read() == -1) { "本机配对凭据损坏" }
                KadbCert.set(certificate, key)
            }
        } else {
            val (certificate, key) = KadbCert.get(cn = "Mutsumi-Focus-local", notAfter = System.currentTimeMillis() + TimeUnit.DAYS.toMillis(3650))
            val output = credentials.startWrite()
            try {
                DataOutputStream(output).apply {
                    writeInt(certificate.size); write(certificate)
                    writeInt(key.size); write(key)
                    flush()
                }
                credentials.finishWrite(output)
            } catch (error: Throwable) {
                credentials.failWrite(output)
                throw error
            }
        }
    }

    override fun close() {
        closed.set(true)
        // Close sockets first so blocking library calls also terminate.
        bridge?.close()
        connection?.close()
    }

    companion object { private val CREDENTIAL_LOCK = Any() }
}

/**
 * Kadb 1.3's pairing socket has no cancellation/timeout API. Relay encrypted
 * bytes unchanged through a single-use local socket, with a hard deadline.
 * TLS + pairing-code authentication still terminate at the phone's adbd.
 */
internal class LoopbackBridge(remotePort: Int, private val deadlineMillis: Long = 35_000) : AutoCloseable {
    private val localhost = InetAddress.getByName("127.0.0.1")
    private val server = ServerSocket(0, 1, localhost)
    private val closed = AtomicBoolean(false)
    private val socketLock = Any()
    private val workers = Executors.newScheduledThreadPool(3) { job ->
        Thread(job, "Mutsumi-local-adb").apply { isDaemon = true }
    }
    @Volatile private var client: Socket? = null
    @Volatile private var upstream: Socket? = null
    val port: Int get() = server.localPort

    init {
        require(remotePort in 1..65535)
        workers.schedule({ close() }, deadlineMillis, TimeUnit.MILLISECONDS)
        workers.execute {
            try {
                server.soTimeout = 4_000
                val accepted = server.accept().also { track(it, isClient = true) }
                server.close()
                val target = Socket().also { track(it, isClient = false) }
                check(!closed.get())
                target.connect(InetSocketAddress(localhost, remotePort), 4_000)
                accepted.soTimeout = 20_000
                target.soTimeout = 20_000
                accepted.tcpNoDelay = true
                target.tcpNoDelay = true
                workers.execute {
                    try { target.getInputStream().copyTo(accepted.getOutputStream()) }
                    catch (_: Exception) { }
                    finally { close() }
                }
                accepted.getInputStream().copyTo(target.getOutputStream())
            } catch (_: Exception) { }
            finally { close() }
        }
    }

    override fun close() {
        synchronized(socketLock) {
            if (!closed.compareAndSet(false, true)) return
            runCatching { server.close() }
            runCatching { client?.close() }
            runCatching { upstream?.close() }
        }
        workers.shutdownNow()
    }

    private fun track(socket: Socket, isClient: Boolean) = synchronized(socketLock) {
        if (closed.get()) { socket.close(); throw IOException("Local transport closed") }
        if (isClient) client = socket else upstream = socket
    }
}
