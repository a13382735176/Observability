plugins {
    kotlin("jvm") version "2.0.21"
    application
}

group = "com.vibe"
version = "1.0.0"

java {
    toolchain {
        languageVersion.set(JavaLanguageVersion.of(21))
    }
}

application {
    mainClass.set("com.vibe.signalrelay.MainKt")
}

dependencies {
    implementation("io.ktor:ktor-server-core-jvm:2.3.12")
    implementation("io.ktor:ktor-server-netty-jvm:2.3.12")
    implementation("ch.qos.logback:logback-classic:1.5.6")
    implementation("org.postgresql:postgresql:42.7.3")
    implementation("com.zaxxer:HikariCP:5.1.0")
    implementation("io.lettuce:lettuce-core:6.3.2.RELEASE")
}

tasks.jar {
    archiveFileName.set("signal-relay-skill.jar")
    manifest {
        attributes["Main-Class"] = application.mainClass.get()
    }
    duplicatesStrategy = DuplicatesStrategy.EXCLUDE
    exclude("META-INF/*.SF", "META-INF/*.DSA", "META-INF/*.RSA")
    from({
        configurations.runtimeClasspath.get().map { if (it.isDirectory) it else zipTree(it) }
    })
}
