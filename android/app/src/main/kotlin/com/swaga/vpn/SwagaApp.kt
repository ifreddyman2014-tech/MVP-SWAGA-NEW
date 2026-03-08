package com.swaga.vpn

import android.app.Application
import com.swaga.vpn.data.AppPreferences
import com.swaga.vpn.api.SwagaApiClient

class SwagaApp : Application() {

    lateinit var prefs: AppPreferences
        private set

    override fun onCreate() {
        super.onCreate()
        instance = this
        prefs = AppPreferences(this)
        SwagaApiClient.init()
    }

    companion object {
        lateinit var instance: SwagaApp
            private set
    }
}
