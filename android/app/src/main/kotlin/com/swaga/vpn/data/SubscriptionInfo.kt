package com.swaga.vpn.data

data class SubscriptionInfo(
    val title: String,
    val username: String,
    val isActive: Boolean,
    val expiryDate: String,
    val daysLeft: Int,
    val vlessLinks: List<String>,
    val subUrl: String,
)
