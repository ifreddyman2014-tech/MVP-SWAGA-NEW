package com.swaga.vpn.ui

import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.swaga.vpn.SwagaApp
import com.swaga.vpn.ui.screens.AuthScreen
import com.swaga.vpn.ui.screens.HomeScreen
import com.swaga.vpn.ui.screens.SplashScreen

object Routes {
    const val SPLASH = "splash"
    const val AUTH   = "auth"
    const val HOME   = "home"
}

@Composable
fun SwagaNavHost() {
    val navController = rememberNavController()

    NavHost(navController = navController, startDestination = Routes.SPLASH) {

        composable(Routes.SPLASH) {
            SplashScreen(
                onHasToken = { navController.navigate(Routes.HOME) { popUpTo(0) } },
                onNoToken  = { navController.navigate(Routes.AUTH) { popUpTo(0) } },
            )
        }

        composable(Routes.AUTH) {
            AuthScreen(
                onSuccess = { navController.navigate(Routes.HOME) { popUpTo(0) } },
            )
        }

        composable(Routes.HOME) {
            HomeScreen(
                onLogout = { navController.navigate(Routes.AUTH) { popUpTo(0) } },
            )
        }
    }
}
