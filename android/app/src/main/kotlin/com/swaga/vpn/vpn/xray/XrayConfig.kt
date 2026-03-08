package com.swaga.vpn.vpn.xray

import com.google.gson.Gson
import com.google.gson.annotations.SerializedName
import java.net.URI
import java.net.URLDecoder

/**
 * Generates xray-core JSON config from a VLESS URL.
 *
 * VLESS URL format:
 *   vless://{uuid}@{host}:{port}?security=reality&...#{name}
 *
 * Output config includes:
 *   - SOCKS5 inbound on 127.0.0.1:SOCKS_PORT (for tun2socks routing)
 *   - VLESS+Reality outbound to the VPN server
 *   - DNS over TLS to 1.1.1.1
 */
object XrayConfig {

    private val gson = Gson()

    fun fromVlessUrl(vlessUrl: String, socksPort: Int): String {
        val uri = URI(vlessUrl)
        val uuid = uri.userInfo
        val host = uri.host
        val port = uri.port

        val params = parseQuery(uri.query)
        val flow        = params["flow"] ?: ""
        val security    = params["security"] ?: "reality"
        val pbk         = params["pbk"] ?: ""
        val sni         = params["sni"] ?: host
        val sid         = params["sid"] ?: ""
        val fp          = params["fp"] ?: "chrome"
        val networkType = params["type"] ?: "tcp"
        val path        = params["path"] ?: ""
        val xhttpHost   = params["host"] ?: ""
        val mode        = params["mode"] ?: ""

        val config = buildConfig(
            uuid        = uuid,
            host        = host,
            port        = port,
            flow        = flow,
            security    = security,
            pbk         = pbk,
            sni         = sni,
            sid         = sid,
            fp          = fp,
            networkType = networkType,
            path        = path,
            xhttpHost   = xhttpHost,
            mode        = mode,
            socksPort   = socksPort,
        )

        return gson.toJson(config)
    }

    private fun parseQuery(query: String?): Map<String, String> {
        if (query.isNullOrBlank()) return emptyMap()
        return query.split("&").associate { pair ->
            val (k, v) = pair.split("=", limit = 2).let {
                it[0] to (it.getOrNull(1) ?: "")
            }
            URLDecoder.decode(k, "UTF-8") to URLDecoder.decode(v, "UTF-8")
        }
    }

    private fun buildConfig(
        uuid: String, host: String, port: Int, flow: String,
        security: String, pbk: String, sni: String, sid: String, fp: String,
        networkType: String, path: String, xhttpHost: String, mode: String,
        socksPort: Int,
    ): Map<String, Any> {
        val streamSettings: MutableMap<String, Any> = mutableMapOf("network" to networkType)

        if (security == "reality") {
            streamSettings["security"] = "reality"
            streamSettings["realitySettings"] = mapOf(
                "serverName" to sni,
                "fingerprint" to fp,
                "publicKey" to pbk,
                "shortId" to sid,
            )
        } else if (security == "tls") {
            streamSettings["security"] = "tls"
            streamSettings["tlsSettings"] = mapOf("serverName" to sni)
        }

        when (networkType) {
            "xhttp", "splithttp" -> {
                val xhttpSettings: MutableMap<String, Any> = mutableMapOf("path" to path)
                if (xhttpHost.isNotBlank()) xhttpSettings["host"] = xhttpHost
                if (mode.isNotBlank()) xhttpSettings["mode"] = mode
                streamSettings["xhttpSettings"] = xhttpSettings
            }
            "ws" -> {
                streamSettings["wsSettings"] = mapOf(
                    "path" to path,
                    "headers" to if (xhttpHost.isNotBlank()) mapOf("Host" to xhttpHost) else emptyMap<String, String>(),
                )
            }
        }

        return mapOf(
            "log" to mapOf("loglevel" to "warning"),

            "inbounds" to listOf(
                mapOf(
                    "tag" to "socks-in",
                    "port" to socksPort,
                    "listen" to "127.0.0.1",
                    "protocol" to "socks",
                    "settings" to mapOf("auth" to "noauth", "udp" to true),
                ),
            ),

            "outbounds" to listOf(
                mapOf(
                    "tag" to "proxy",
                    "protocol" to "vless",
                    "settings" to mapOf(
                        "vnext" to listOf(
                            mapOf(
                                "address" to host,
                                "port" to port,
                                "users" to listOf(
                                    buildMap<String, Any> {
                                        put("id", uuid)
                                        put("encryption", "none")
                                        if (flow.isNotBlank()) put("flow", flow)
                                    }
                                ),
                            )
                        )
                    ),
                    "streamSettings" to streamSettings,
                ),
                mapOf("tag" to "direct", "protocol" to "freedom"),
                mapOf("tag" to "block",  "protocol" to "blackhole"),
            ),

            "routing" to mapOf(
                "domainStrategy" to "IPIfNonMatch",
                "rules" to listOf(
                    mapOf("type" to "field", "ip" to listOf("geoip:private"), "outboundTag" to "direct"),
                ),
            ),

            "dns" to mapOf(
                "servers" to listOf("1.1.1.1", "8.8.8.8"),
            ),
        )
    }
}
