package com.swaga.vpn.vpn

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.net.VpnService
import android.os.Build
import android.os.ParcelFileDescriptor
import android.util.Log
import androidx.core.app.NotificationCompat
import com.swaga.vpn.MainActivity
import com.swaga.vpn.R
import com.swaga.vpn.vpn.xray.XrayConfig
import com.swaga.vpn.vpn.xray.XrayRunner
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import java.net.InetAddress

/**
 * Android VpnService that routes device traffic through a local SOCKS5 proxy
 * served by xray-core (running as a coroutine on the device).
 *
 * Traffic flow:
 *   App → tun interface → tun2socks → SOCKS5:10808 → xray-core → VLESS server
 *
 * NOTE: tun2socks is not bundled here — xray can also serve as a transparent
 * proxy via its dokodemo-door inbound. For full routing we recommend shipping
 * libxray.aar from the v2rayNG project and calling Libv2ray.startV2Ray().
 */
class SwagaVpnService : VpnService() {

    companion object {
        const val ACTION_CONNECT    = "com.swaga.vpn.CONNECT"
        const val ACTION_DISCONNECT = "com.swaga.vpn.DISCONNECT"
        const val EXTRA_VLESS_URL   = "vless_url"

        private const val TAG            = "SwagaVpnService"
        private const val NOTIF_CHANNEL  = "swaga_vpn"
        private const val NOTIF_ID       = 1001
        private const val SOCKS5_PORT    = 10808
        private const val DNS_PORT       = 10853
    }

    private val scope  = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private var tun: ParcelFileDescriptor? = null
    private var xrayRunner: XrayRunner? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_CONNECT    -> startVpn(intent.getStringExtra(EXTRA_VLESS_URL) ?: "")
            ACTION_DISCONNECT -> stopVpn()
        }
        return START_NOT_STICKY
    }

    private fun startVpn(vlessUrl: String) {
        if (vlessUrl.isBlank()) { stopVpn(); return }

        startForeground(NOTIF_ID, buildNotification("Подключение..."))
        VpnController.updateState(VpnState.CONNECTING)

        scope.launch {
            try {
                // 1. Generate xray config from VLESS URL
                val config = XrayConfig.fromVlessUrl(vlessUrl, socksPort = SOCKS5_PORT)

                // 2. Start xray-core
                xrayRunner = XrayRunner().also { it.start(config) }

                // 3. Build TUN interface
                tun = Builder()
                    .setSession("SwagaVPN")
                    .addAddress("10.0.0.2", 24)
                    .addRoute("0.0.0.0", 0)
                    .addDnsServer(InetAddress.getByName("1.1.1.1"))
                    .setMtu(1500)
                    .establish()

                if (tun == null) {
                    Log.e(TAG, "Failed to establish TUN interface")
                    stopVpn()
                    return@launch
                }

                VpnController.updateState(VpnState.CONNECTED)
                updateNotification("Подключено — защита активна")

                Log.i(TAG, "VPN started, TUN fd=${tun!!.fd}")

            } catch (e: Exception) {
                Log.e(TAG, "VPN start error", e)
                VpnController.updateState(VpnState.ERROR)
                stopVpn()
            }
        }
    }

    private fun stopVpn() {
        Log.i(TAG, "Stopping VPN")
        xrayRunner?.stop()
        xrayRunner = null

        tun?.close()
        tun = null

        VpnController.updateState(VpnState.DISCONNECTED)
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onDestroy() {
        super.onDestroy()
        stopVpn()
    }

    // ─── Notifications ─────────────────────────────────────────────────────────

    private fun buildNotification(text: String): Notification {
        createNotificationChannel()

        val stopIntent = Intent(this, SwagaVpnService::class.java).apply { action = ACTION_DISCONNECT }
        val stopPending = PendingIntent.getService(
            this, 0, stopIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        val openIntent = PendingIntent.getActivity(
            this, 0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        return NotificationCompat.Builder(this, NOTIF_CHANNEL)
            .setContentTitle("SWAGA VPN")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_lock_lock)
            .setContentIntent(openIntent)
            .addAction(android.R.drawable.ic_delete, "Отключить", stopPending)
            .setOngoing(true)
            .build()
    }

    private fun updateNotification(text: String) {
        val nm = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        nm.notify(NOTIF_ID, buildNotification(text))
    }

    private fun createNotificationChannel() {
        val channel = NotificationChannel(
            NOTIF_CHANNEL,
            "SWAGA VPN",
            NotificationManager.IMPORTANCE_LOW,
        ).apply { description = "VPN connection status" }
        (getSystemService(NOTIFICATION_SERVICE) as NotificationManager).createNotificationChannel(channel)
    }
}
