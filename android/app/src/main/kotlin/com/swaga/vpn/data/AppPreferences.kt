package com.swaga.vpn.data

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

private val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "swaga_prefs")

class AppPreferences(private val context: Context) {

    companion object {
        val KEY_SUB_TOKEN    = stringPreferencesKey("sub_token")
        val KEY_SUB_BASE_URL = stringPreferencesKey("sub_base_url")
    }

    val subToken: Flow<String?> = context.dataStore.data.map { it[KEY_SUB_TOKEN] }
    val subBaseUrl: Flow<String?> = context.dataStore.data.map { it[KEY_SUB_BASE_URL] }

    suspend fun saveSubscription(baseUrl: String, token: String) {
        context.dataStore.edit { prefs ->
            prefs[KEY_SUB_BASE_URL] = baseUrl.trimEnd('/')
            prefs[KEY_SUB_TOKEN]    = token
        }
    }

    suspend fun clear() {
        context.dataStore.edit { it.clear() }
    }
}
