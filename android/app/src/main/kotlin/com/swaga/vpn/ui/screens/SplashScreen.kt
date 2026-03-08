package com.swaga.vpn.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.swaga.vpn.SwagaApp
import com.swaga.vpn.ui.theme.AccentBlueBright
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first

@Composable
fun SplashScreen(
    onHasToken: () -> Unit,
    onNoToken: () -> Unit,
) {
    val prefs = SwagaApp.instance.prefs

    LaunchedEffect(Unit) {
        delay(800)
        val token = prefs.subToken.first()
        if (token.isNullOrBlank()) onNoToken() else onHasToken()
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background),
        contentAlignment = Alignment.Center,
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(
                text = "🛡",
                fontSize = 64.sp,
            )
            Spacer(Modifier.height(16.dp))
            Text(
                text = "SWAGA VPN",
                style = MaterialTheme.typography.headlineLarge,
                fontWeight = FontWeight.Bold,
                color = AccentBlueBright,
            )
            Spacer(Modifier.height(8.dp))
            Text(
                text = "Безопасный интернет",
                style = MaterialTheme.typography.bodyMedium,
            )
        }
    }
}
