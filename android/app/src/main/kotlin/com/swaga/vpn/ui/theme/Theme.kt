package com.swaga.vpn.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

val DarkBackground   = Color(0xFF0F0F13)
val DarkSurface      = Color(0xFF1C1C24)
val DarkSurface2     = Color(0xFF252530)
val AccentBlue       = Color(0xFF1976D2)
val AccentBlueBright = Color(0xFF64B5F6)
val GreenActive      = Color(0xFF4CAF50)
val RedInactive      = Color(0xFFF44336)
val TextPrimary      = Color(0xFFE0E0E0)
val TextSecondary    = Color(0xFF888888)

private val SwagaColorScheme = darkColorScheme(
    primary          = AccentBlue,
    onPrimary        = Color.White,
    primaryContainer = Color(0xFF1565C0),
    secondary        = AccentBlueBright,
    background       = DarkBackground,
    surface          = DarkSurface,
    surfaceVariant   = DarkSurface2,
    onBackground     = TextPrimary,
    onSurface        = TextPrimary,
    onSurfaceVariant = TextSecondary,
    error            = RedInactive,
)

@Composable
fun SwagaTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = SwagaColorScheme,
        typography  = SwagaTypography,
        content     = content,
    )
}
