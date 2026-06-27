plugins {
    kotlin("jvm") version "1.9.24"
    application
}
application { mainClass.set("ApplicationKt") }
repositories { mavenCentral() }
dependencies {
    implementation("io.ktor:ktor-server-netty:2.3.12")
    implementation("io.ktor:ktor-server-content-negotiation:2.3.12")
    implementation("io.ktor:ktor-serialization-kotlinx-json:2.3.12")
    implementation("ch.qos.logback:logback-classic:1.5.6")
    implementation("org.postgresql:postgresql:42.7.3")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.6.3")
}
tasks.jar {
    manifest { attributes["Main-Class"] = "ApplicationKt" }
    from(configurations.runtimeClasspath.get().map { if (it.isDirectory) it else zipTree(it) })
    duplicatesStrategy = DuplicatesStrategy.EXCLUDE
}
