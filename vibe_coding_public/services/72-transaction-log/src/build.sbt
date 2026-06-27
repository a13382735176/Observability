val http4sVersion = "0.23.27"
val doobieVersion = "1.0.0-RC4"

lazy val root = (project in file("."))
  .settings(
    name := "transaction-log",
    version := "0.1.0",
    scalaVersion := "3.3.3",
    libraryDependencies ++= Seq(
      "org.http4s" %% "http4s-ember-server" % http4sVersion,
      "org.http4s" %% "http4s-dsl" % http4sVersion,
      "org.http4s" %% "http4s-circe" % http4sVersion,
      "io.circe" %% "circe-generic" % "0.14.9",
      "org.tpolecat" %% "doobie-core" % doobieVersion,
      "org.tpolecat" %% "doobie-postgres" % doobieVersion,
      "redis.clients" % "jedis" % "5.1.3",
      "ch.qos.logback" % "logback-classic" % "1.5.6",
      "com.comcast" %% "ip4s-core" % "3.4.0"
    ),
    assembly / assemblyJarName := "transaction-log.jar",
    assembly / assemblyMergeStrategy := {
      case PathList("META-INF", xs @ _*) => MergeStrategy.discard
      case x => MergeStrategy.first
    }
  )
