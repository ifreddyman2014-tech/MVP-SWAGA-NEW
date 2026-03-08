package com.swaga.vpn

import android.net.VpnService
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import com.swaga.vpn.ui.SwagaNavHost
import com.swaga.vpn.ui.theme.SwagaTheme
import com.swaga.vpn.vpn.VpnController
import kotlinx.coroutines.flow.MutableStateFlow

class MainActivity : ComponentActivity() {

    val vpnPermissionResult = MutableStateFlow<Boolean?>(null)

    private val vpnPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        vpnPermissionResult.value = result.resultCode == RESULT_OK
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        VpnController.init(this)

        setContent {
            SwagaTheme {
                SwagaNavHost()
            }
        }
    }

    fun requestVpnPermission() {
        val intent = VpnService.prepare(this)
        if (intent == null) {
            vpnPermissionResult.value = true
        } else {
            vpnPermissionLauncher.launch(intent)
        }
    }
}
