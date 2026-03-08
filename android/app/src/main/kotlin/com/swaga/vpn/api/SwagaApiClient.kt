package com.swaga.vpn.api

import android.util.Base64
import com.swaga.vpn.data.SubscriptionInfo
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.logging.HttpLoggingInterceptor
import java.util.concurrent.TimeUnit

/**
 * Fetches subscription data from /sub/{token} endpoint.
 *
 * The endpoint returns:
 *   - Body: base64-encoded newline-separated VLESS links
 *   - Header profile-title: subscription name
 *   - Header subscription-userinfo: upload=0; download=X; total=Y; expire=UNIX_TS
 */
object SwagaApiClient {

    private lateinit var client: OkHttpClient

    fun init() {
        val logging = HttpLoggingInterceptor().apply {
            level = HttpLoggingInterceptor.Level.HEADERS
        }
        client = OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .addInterceptor(logging)
            .addInterceptor { chain ->
                // Identify ourselves so server knows it's the app, not V2RayTun
                chain.proceed(
                    chain.request().newBuilder()
                        .header("User-Agent", "SwagaVPN-Android/1.0")
                        .build()
                )
            }
            .build()
    }

    /**
     * Fetches and parses the subscription.
     * @param baseUrl e.g. "https://sub.swaga-vpn.ru"
     * @param token   the sub_token UUID
     */
    suspend fun fetchSubscription(baseUrl: String, token: String): Result<SubscriptionInfo> {
        return runCatching {
            val subUrl = "$baseUrl/sub/$token"
            val request = Request.Builder().url(subUrl).get().build()

            val response = client.newCall(request).execute()

            if (!response.isSuccessful) {
                error("Server returned ${response.code}")
            }

            val body = response.body?.string() ?: error("Empty response body")

            // Decode base64 VLESS links
            val decoded = String(Base64.decode(body.trim(), Base64.DEFAULT))
            val vlessLinks = decoded.lines().filter { it.startsWith("vless://") }

            if (vlessLinks.isEmpty()) error("No VLESS links in subscription")

            // Parse profile headers
            val title = response.header("profile-title") ?: "SWAGA VPN"
            val userInfo = response.header("subscription-userinfo") ?: ""

            // Parse expire from userinfo: "upload=0; download=X; total=Y; expire=TS"
            val expireTs = userInfo.split(";")
                .map { it.trim() }
                .firstOrNull { it.startsWith("expire=") }
                ?.removePrefix("expire=")
                ?.toLongOrNull()

            val (expiryStr, daysLeft, isActive) = if (expireTs != null) {
                val now = System.currentTimeMillis() / 1000
                val days = ((expireTs - now) / 86400).toInt().coerceAtLeast(0)
                val date = java.text.SimpleDateFormat("dd.MM.yyyy", java.util.Locale.getDefault())
                    .format(java.util.Date(expireTs * 1000))
                Triple(date, days, expireTs > now)
            } else {
                Triple("—", 0, true)
            }

            SubscriptionInfo(
                title       = title,
                username    = token.take(8),  // Short identifier from token prefix
                isActive    = isActive,
                expiryDate  = expiryStr,
                daysLeft    = daysLeft,
                vlessLinks  = vlessLinks,
                subUrl      = subUrl,
            )
        }
    }
}
