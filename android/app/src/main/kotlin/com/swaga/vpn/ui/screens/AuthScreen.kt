package com.swaga.vpn.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.swaga.vpn.SwagaApp
import com.swaga.vpn.api.SwagaApiClient
import com.swaga.vpn.ui.theme.*
import kotlinx.coroutines.launch

/**
 * Auth screen — user pastes their subscription URL or token.
 *
 * Accepts two formats:
 *   1. Full URL: https://sub.swaga-vpn.ru/sub/xxxxxxxx-xxxx-...
 *   2. Token only: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
 */
@Composable
fun AuthScreen(onSuccess: () -> Unit) {
    val prefs   = SwagaApp.instance.prefs
    val scope   = rememberCoroutineScope()
    val keyboard = LocalSoftwareKeyboardController.current

    var input   by remember { mutableStateOf("") }
    var loading by remember { mutableStateOf(false) }
    var error   by remember { mutableStateOf<String?>(null) }

    fun connect() {
        error = null
        val trimmed = input.trim()
        if (trimmed.isBlank()) { error = "Введи ссылку или токен"; return }

        // Parse base URL and token
        val (baseUrl, token) = parseInput(trimmed) ?: run {
            error = "Неверный формат. Ожидается ссылка /sub/UUID или UUID"
            return
        }

        loading = true
        keyboard?.hide()

        scope.launch {
            val result = SwagaApiClient.fetchSubscription(baseUrl, token)
            loading = false

            result.fold(
                onSuccess = {
                    prefs.saveSubscription(baseUrl, token)
                    onSuccess()
                },
                onFailure = {
                    error = "Не удалось подключиться: ${it.message}"
                },
            )
        }
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
            .padding(24.dp),
    ) {
        Column(
            modifier = Modifier.align(Alignment.Center),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text("🛡", fontSize = 56.sp)
            Spacer(Modifier.height(16.dp))
            Text(
                "SWAGA VPN",
                style = MaterialTheme.typography.headlineMedium,
                color = AccentBlueBright,
                fontWeight = FontWeight.Bold,
            )
            Spacer(Modifier.height(8.dp))
            Text(
                "Вставь ссылку подписки из бота",
                style = MaterialTheme.typography.bodyMedium,
                textAlign = TextAlign.Center,
            )

            Spacer(Modifier.height(32.dp))

            OutlinedTextField(
                value = input,
                onValueChange = { input = it; error = null },
                modifier = Modifier.fillMaxWidth(),
                placeholder = { Text("https://sub.swaga-vpn.ru/sub/...", style = MaterialTheme.typography.bodyMedium) },
                singleLine = false,
                maxLines = 3,
                isError = error != null,
                supportingText = error?.let { { Text(it, color = MaterialTheme.colorScheme.error) } },
                keyboardOptions = KeyboardOptions(
                    keyboardType = KeyboardType.Uri,
                    imeAction    = ImeAction.Done,
                ),
                keyboardActions = KeyboardActions(onDone = { connect() }),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor   = AccentBlue,
                    unfocusedBorderColor = DarkSurface2,
                    focusedContainerColor   = DarkSurface,
                    unfocusedContainerColor = DarkSurface,
                ),
            )

            Spacer(Modifier.height(16.dp))

            Button(
                onClick  = { connect() },
                modifier = Modifier
                    .fillMaxWidth()
                    .height(52.dp),
                enabled  = !loading,
                colors   = ButtonDefaults.buttonColors(containerColor = AccentBlue),
                shape    = MaterialTheme.shapes.medium,
            ) {
                if (loading) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(22.dp),
                        color = MaterialTheme.colorScheme.onPrimary,
                        strokeWidth = 2.dp,
                    )
                } else {
                    Text("Подключиться", fontWeight = FontWeight.SemiBold)
                }
            }

            Spacer(Modifier.height(24.dp))

            Text(
                "Ссылку подписки можно получить в боте:\n@Swaga_vpnbot",
                style = MaterialTheme.typography.bodyMedium,
                textAlign = TextAlign.Center,
                color = TextSecondary,
            )
        }
    }
}

/**
 * Parses user input into (baseUrl, token).
 * Supports:
 *   - https://sub.swaga-vpn.ru/sub/UUID
 *   - UUID (uses default base URL)
 */
private fun parseInput(input: String): Pair<String, String>? {
    // Full URL format
    val subPathRegex = Regex("""^(https?://[^/]+)/sub/([0-9a-fA-F-]{36})$""")
    subPathRegex.matchEntire(input)?.let { m ->
        return m.groupValues[1] to m.groupValues[2]
    }

    // Bare UUID
    val uuidRegex = Regex("""^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$""")
    if (uuidRegex.matches(input)) {
        return "https://sub.swaga-vpn.ru" to input
    }

    return null
}
