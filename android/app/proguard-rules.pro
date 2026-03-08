# Keep xray-core AAR classes (when integrated)
-keep class libxray.** { *; }
-keep class com.v2ray.** { *; }

# Keep Gson model classes
-keepattributes Signature
-keepattributes *Annotation*
-keep class com.google.gson.** { *; }

# Keep our data classes
-keep class com.swaga.vpn.data.** { *; }
