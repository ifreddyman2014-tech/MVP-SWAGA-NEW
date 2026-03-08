package com.swaga.vpn.ui.screens

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.*
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Logout
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.swaga.vpn.SwagaApp
import com.swaga.vpn.api.SwagaApiClient
import com.swaga.vpn.data.SubscriptionInfo
import com.swaga.vpn.ui.theme.*
import com.swaga.vpn.vpn.VpnController
import com.swaga.vpn.vpn.VpnState
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen(onLogout: () -> Unit) {
    val prefs = SwagaApp.instance.prefs
    val scope = rememberCoroutineScope()

    var subInfo  by remember { mutableStateOf<SubscriptionInfo?>(null) }
    var loading  by remember { mutableStateOf(true) }
    var error    by remember { mutableStateOf<String?>(null) }

    val vpnState by VpnController.state.collectAsState()

    // Load subscription on first composition
    LaunchedEffect(Unit) {
        refreshSubscription(prefs, onRefreshed = { subInfo = it }, onError = { error = it })
        loading = false
    }

    suspend fun refresh() {
        loading = true
        error = null
        refreshSubscription(prefs, onRefreshed = { subInfo = it }, onError = { error = it })
        loading = false
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text("SWAGA VPN", fontWeight = FontWeight.Bold, color = AccentBlueBright)
                },
                actions = {
                    IconButton(onClick = { scope.launch { refresh() } }, enabled = !loading) {
                        Icon(Icons.Default.Refresh, contentDescription = "Обновить", tint = AccentBlueBright)
                    }
                    IconButton(onClick = {
                        scope.launch {
                            VpnController.disconnect()
                            prefs.clear()
                            onLogout()
                        }
                    }) {
                        Icon(Icons.Default.Logout, contentDescription = "Выйти", tint = TextSecondary)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = DarkBackground),
            )
        },
        containerColor = DarkBackground,
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(horizontal = 16.dp)
                .verticalScroll(rememberScrollState()),
        ) {
            Spacer(Modifier.height(8.dp))

            when {
                loading && subInfo == null -> {
                    Box(Modifier.fillMaxWidth().height(200.dp), contentAlignment = Alignment.Center) {
                        CircularProgressIndicator(color = AccentBlue)
                    }
                }
                error != null && subInfo == null -> {
                    ErrorCard(error!!, onRetry = { scope.launch { refresh() } })
                }
                subInfo != null -> {
                    SubscriptionCard(subInfo!!)
                    Spacer(Modifier.height(16.dp))
                    ConnectButton(
                        vpnState = vpnState,
                        vlessLinks = subInfo!!.vlessLinks,
                    )
                    Spacer(Modifier.height(16.dp))
                    ServerListCard(subInfo!!.vlessLinks)
                }
            }

            Spacer(Modifier.height(24.dp))
        }
    }
}

@Composable
private fun SubscriptionCard(info: SubscriptionInfo) {
    val statusColor = if (info.isActive) GreenActive else RedInactive

    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape    = RoundedCornerShape(16.dp),
        color    = DarkSurface,
    ) {
        Column(Modifier.padding(20.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    Modifier
                        .size(10.dp)
                        .clip(CircleShape)
                        .background(statusColor)
                )
                Spacer(Modifier.width(10.dp))
                Column {
                    Text(info.title, style = MaterialTheme.typography.titleMedium)
                    Text(
                        if (info.isActive) "Истекает через ${info.daysLeft} дн." else "Подписка истекла",
                        style = MaterialTheme.typography.bodyMedium,
                    )
                }
            }

            Spacer(Modifier.height(16.dp))

            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                InfoBox(Modifier.weight(1f), "Статус", if (info.isActive) "Активна" else "Истекла", statusColor)
                InfoBox(Modifier.weight(1f), "Истекает", info.expiryDate)
            }
            Spacer(Modifier.height(10.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                InfoBox(Modifier.weight(1f), "Серверов", "${info.vlessLinks.size}")
                InfoBox(Modifier.weight(1f), "Трафик", "∞")
            }
        }
    }
}

@Composable
private fun InfoBox(modifier: Modifier, label: String, value: String, valueColor: Color = TextPrimary) {
    Surface(modifier, shape = RoundedCornerShape(10.dp), color = DarkSurface2) {
        Column(Modifier.padding(14.dp)) {
            Text(label.uppercase(), style = MaterialTheme.typography.labelSmall)
            Spacer(Modifier.height(4.dp))
            Text(value, style = MaterialTheme.typography.titleMedium, color = valueColor)
        }
    }
}

@Composable
private fun ConnectButton(vpnState: VpnState, vlessLinks: List<String>) {
    val scope = rememberCoroutineScope()

    val isConnected   = vpnState == VpnState.CONNECTED
    val isConnecting  = vpnState == VpnState.CONNECTING

    val btnColor by animateColorAsState(
        targetValue = when (vpnState) {
            VpnState.CONNECTED  -> GreenActive
            VpnState.CONNECTING -> AccentBlueBright.copy(alpha = .7f)
            else                -> AccentBlue
        },
        label = "btnColor",
    )

    val pulse = rememberInfiniteTransition(label = "pulse")
    val scale by pulse.animateFloat(
        initialValue = 1f,
        targetValue  = if (isConnecting) 1.04f else 1f,
        animationSpec = infiniteRepeatable(tween(700), RepeatMode.Reverse),
        label = "scale",
    )

    Button(
        onClick = {
            scope.launch {
                if (isConnected) VpnController.disconnect()
                else VpnController.connect(vlessLinks.first())
            }
        },
        modifier = Modifier
            .fillMaxWidth()
            .height(64.dp)
            .scale(scale),
        enabled = !isConnecting,
        colors  = ButtonDefaults.buttonColors(containerColor = btnColor),
        shape   = RoundedCornerShape(16.dp),
    ) {
        Text(
            text = when (vpnState) {
                VpnState.CONNECTED  -> "⏹  Отключиться"
                VpnState.CONNECTING -> "Подключение..."
                else                -> "▶  Подключиться"
            },
            fontSize    = 18.sp,
            fontWeight  = FontWeight.Bold,
        )
    }
}

@Composable
private fun ServerListCard(vlessLinks: List<String>) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape    = RoundedCornerShape(16.dp),
        color    = DarkSurface,
    ) {
        Column(Modifier.padding(20.dp)) {
            Text("Серверы", style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.height(12.dp))
            vlessLinks.forEachIndexed { i, link ->
                val serverName = extractServerName(link)
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Box(
                        Modifier
                            .size(8.dp)
                            .clip(CircleShape)
                            .background(GreenActive)
                    )
                    Spacer(Modifier.width(12.dp))
                    Text(serverName, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
                    Text("${i + 1}", style = MaterialTheme.typography.bodyMedium)
                }
                if (i < vlessLinks.lastIndex) HorizontalDivider(color = DarkSurface2, thickness = 1.dp)
            }
        }
    }
}

@Composable
private fun ErrorCard(message: String, onRetry: () -> Unit) {
    Surface(Modifier.fillMaxWidth(), shape = RoundedCornerShape(16.dp), color = DarkSurface) {
        Column(Modifier.padding(20.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Text("⚠️", fontSize = 32.sp)
            Spacer(Modifier.height(8.dp))
            Text(message, style = MaterialTheme.typography.bodyMedium, color = RedInactive)
            Spacer(Modifier.height(16.dp))
            OutlinedButton(onClick = onRetry) { Text("Попробовать снова") }
        }
    }
}

private fun extractServerName(vlessLink: String): String {
    val fragment = vlessLink.substringAfterLast("#")
    return java.net.URLDecoder.decode(fragment, "UTF-8").ifBlank { "Сервер" }
}

private suspend fun refreshSubscription(
    prefs: com.swaga.vpn.data.AppPreferences,
    onRefreshed: (SubscriptionInfo) -> Unit,
    onError: (String) -> Unit,
) {
    val baseUrl = prefs.subBaseUrl.first() ?: return onError("Подписка не найдена")
    val token   = prefs.subToken.first()   ?: return onError("Токен не найден")

    SwagaApiClient.fetchSubscription(baseUrl, token).fold(
        onSuccess = onRefreshed,
        onFailure = { onError(it.message ?: "Ошибка загрузки") },
    )
}
