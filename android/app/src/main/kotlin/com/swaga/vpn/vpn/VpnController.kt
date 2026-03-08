package com.swaga.vpn.vpn

import android.content.Context
import android.content.Intent
import com.swaga.vpn.MainActivity
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first

/**
 * Singleton controller that bridges UI ↔ SwagaVpnService.
 *
 * VPN lifecycle:
 *   connect(vlessUrl) → requests VPN permission (if needed) → starts SwagaVpnService
 *   disconnect()      → stops SwagaVpnService
 *
 * State is published via [state] StateFlow so Compose can react.
 */
object VpnController {

    private val _state = MutableStateFlow(VpnState.DISCONNECTED)
    val state: StateFlow<VpnState> = _state.asStateFlow()

    private var appContext: Context? = null
    private var activity: MainActivity? = null

    fun init(activity: MainActivity) {
        this.activity = activity
        this.appContext = activity.applicationContext
    }

    /** Called by SwagaVpnService to report state changes. */
    fun updateState(newState: VpnState) {
        _state.value = newState
    }

    suspend fun connect(vlessUrl: String) {
        val ctx = appContext ?: return
        val act = activity  ?: return

        _state.value = VpnState.CONNECTING

        // Request VPN permission
        act.requestVpnPermission()
        val granted = act.vpnPermissionResult.first { it != null } ?: false
        act.vpnPermissionResult.value = null  // reset

        if (!granted) {
            _state.value = VpnState.DISCONNECTED
            return
        }

        // Start the service
        val intent = Intent(ctx, SwagaVpnService::class.java).apply {
            action = SwagaVpnService.ACTION_CONNECT
            putExtra(SwagaVpnService.EXTRA_VLESS_URL, vlessUrl)
        }
        ctx.startForegroundService(intent)
    }

    fun disconnect() {
        val ctx = appContext ?: return
        val intent = Intent(ctx, SwagaVpnService::class.java).apply {
            action = SwagaVpnService.ACTION_DISCONNECT
        }
        ctx.startService(intent)
    }
}
