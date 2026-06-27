plugins {
    kotlin("jvm") version "1.9.24"
    kotlin("plugin.serialization") version "1.9.24"
    application
    id("com.github.johnrengelman.shadow") version "8.1.1"
}

repositories {
    mavenCentral()
}

dependencies {
    implementation("io.ktor:ktor-server-core:2.3.12")
    implementation("io.ktor:ktor-server-netty:2.3.12")
    implementation("io.ktor:ktor-server-content-negotiation:2.3.12")
    implementation("io.ktor:ktor-serialization-kotlinx-json:2.3.12")
    implementation("ch.qos.logback:logback-classic:1.5.6")
    implementation("redis.clients:jedis:5.1.3")
}

application {
    mainClass.set("com.vibe.cb.AppKt")
}

tasks.shadowJar {
    archiveBaseName.set("app")
    archiveClassifier.set("")
    archiveVersion.set("")
    manifest { attributes(mapOf("Main-Class" to "com.vibe.cb.AppKt")) }
}
