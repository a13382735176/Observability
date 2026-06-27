plugins {
    kotlin("jvm") version "1.9.24"
    application
}
application { mainClass.set("com.vibe.ApplicationKt") }
repositories { mavenCentral() }
dependencies {
    implementation("io.ktor:ktor-server-netty:2.3.12")
    implementation("io.ktor:ktor-server-content-negotiation:2.3.12")
    implementation("io.ktor:ktor-serialization-kotlinx-json:2.3.12")
    implementation("ch.qos.logback:logback-classic:1.5.6")
    implementation("redis.clients:jedis:5.1.3")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.6.3")
}
