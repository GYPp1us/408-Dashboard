package com.mutsumi.focus.localadb

import org.junit.Assert.*
import org.junit.Test
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class LoopbackBridgeTest {
    @Test fun relaysBytesUnchangedAndClosesPeerWhenFinished() {
        ServerSocket(0, 1, InetAddress.getByName("127.0.0.1")).use { server ->
            val complete = CountDownLatch(1)
            val peer = Thread {
                server.accept().use { socket ->
                    socket.soTimeout = 3000
                    val bytes = ByteArray(4)
                    java.io.DataInputStream(socket.getInputStream()).readFully(bytes)
                    socket.getOutputStream().write(bytes)
                    assertEquals(-1, socket.getInputStream().read())
                }
                complete.countDown()
            }.apply { isDaemon = true; start() }
            LoopbackBridge(server.localPort).use { bridge ->
                Socket("127.0.0.1", bridge.port).use { socket ->
                    socket.soTimeout = 3000
                    val original = byteArrayOf(0, 1, -1, 42)
                    socket.getOutputStream().write(original)
                    val received = ByteArray(4)
                    java.io.DataInputStream(socket.getInputStream()).readFully(received)
                    assertArrayEquals(original, received)
                }
            }
            assertTrue(complete.await(3, TimeUnit.SECONDS))
            peer.join(1000)
        }
    }

    @Test fun deadlineClosesStalledTransport() {
        ServerSocket(0, 1, InetAddress.getByName("127.0.0.1")).use { server ->
            LoopbackBridge(server.localPort, deadlineMillis = 500).use { bridge ->
                Socket("127.0.0.1", bridge.port).use { local ->
                    local.soTimeout = 3000
                    server.soTimeout = 3000
                    server.accept().use { remote ->
                        remote.soTimeout = 3000
                        assertEquals(-1, local.getInputStream().read())
                        assertEquals(-1, remote.getInputStream().read())
                    }
                }
            }
        }
    }
}
