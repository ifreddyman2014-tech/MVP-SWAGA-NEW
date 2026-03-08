package com.swaga.vpn.vpn.xray

import android.util.Log

/**
 * Wraps the xray-core native library.
 *
 * Integration options (choose one):
 *
 * Option A — libxray.aar (recommended):
 *   1. Download libxray.aar from https://github.com/xtls/libxray/releases
 *   2. Place in android/app/libs/libxray.aar
 *   3. Uncomment the dependency in app/build.gradle.kts
 *   4. Replace the stub calls below with: Libxray.runXray(configJson)
 *
 * Option B — libv2ray.aar (v2rayNG style):
 *   Uses go.mobile binding. Import from v2rayNG project.
 *   Call: V2RayVPNServiceHandler.startV2Ray(configJson)
 *
 * Option C — xray binary (root only):
 *   Run xray as a child process with Runtime.exec().
 *
 * The stub below logs the config and simulates running so the app compiles
 * and the UI works. Replace with real calls before shipping.
 */
class XrayRunner {

    private var running = false

    fun start(configJson: String) {
        if (running) return
        Log.i(TAG, "Starting xray-core...")
        Log.d(TAG, "Config: ${configJson.take(200)}...")

        /*
         * ─── REPLACE WITH REAL CALL ─────────────────────────────────────
         * import libxray.Libxray
         * Libxray.runXray(configJson)
         * ────────────────────────────────────────────────────────────────
         */

        running = true
        Log.i(TAG, "xray-core started (stub)")
    }

    fun stop() {
        if (!running) return
        Log.i(TAG, "Stopping xray-core...")

        /*
         * ─── REPLACE WITH REAL CALL ─────────────────────────────────────
         * Libxray.stopXray()
         * ────────────────────────────────────────────────────────────────
         */

        running = false
        Log.i(TAG, "xray-core stopped (stub)")
    }

    companion object {
        private const val TAG = "XrayRunner"
    }
}
