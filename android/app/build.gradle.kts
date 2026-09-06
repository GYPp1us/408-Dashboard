import java.util.Properties

plugins {
    id("com.android.application")
}

val localSigningProperties = Properties().apply {
    val propertiesFile = rootProject.file("../.signing/release.properties")
    if (propertiesFile.exists()) propertiesFile.inputStream().use(::load)
}
fun signingValue(environmentName: String, propertyName: String): String? =
    providers.environmentVariable(environmentName).orNull ?: localSigningProperties.getProperty(propertyName)

val releaseStoreFilePath = signingValue("MUTSUMI_FOCUS_STORE_FILE", "storeFile")
val releaseStorePassword = signingValue("MUTSUMI_FOCUS_STORE_PASSWORD", "storePassword")
val releaseKeyAlias = signingValue("MUTSUMI_FOCUS_KEY_ALIAS", "keyAlias")
val releaseKeyPassword = signingValue("MUTSUMI_FOCUS_KEY_PASSWORD", "keyPassword")
val releaseSigningReady = listOf(
    releaseStoreFilePath,
    releaseStorePassword,
    releaseKeyAlias,
    releaseKeyPassword,
).all { !it.isNullOrBlank() }
val dashboardUrl = providers.environmentVariable("MUTSUMI_FOCUS_URL").orNull
    ?: "https://platform.arcol.site/"
val vivoAtomicScene = providers.environmentVariable("MUTSUMI_VIVO_ATOMIC_SCENE").orNull
    ?: "FOCUS_TIMER"

android {
    namespace = "com.mutsumi.focus"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.mutsumi.focus"
        minSdk = 26
        targetSdk = 36
        versionCode = 2
        versionName = "0.2.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        buildConfigField("String", "DASHBOARD_URL", "\"$dashboardUrl\"")
        buildConfigField("String", "VIVO_ATOMIC_SCENE", "\"$vivoAtomicScene\"")
    }

    signingConfigs {
        create("release") {
            if (releaseSigningReady) {
                storeFile = file(requireNotNull(releaseStoreFilePath))
                storePassword = releaseStorePassword
                keyAlias = releaseKeyAlias
                keyPassword = releaseKeyPassword
            }
        }
    }

    buildTypes {
        debug {
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"
        }
        release {
            isMinifyEnabled = false
            if (releaseSigningReady) signingConfig = signingConfigs.getByName("release")
        }
    }

    buildFeatures {
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    testOptions {
        unitTests.isReturnDefaultValues = true
    }
}

tasks.register("checkReleaseSigning") {
    doLast {
        check(releaseSigningReady) {
            "Release signing requires MUTSUMI_FOCUS_STORE_FILE, MUTSUMI_FOCUS_STORE_PASSWORD, MUTSUMI_FOCUS_KEY_ALIAS and MUTSUMI_FOCUS_KEY_PASSWORD"
        }
        check(file(requireNotNull(releaseStoreFilePath)).exists()) {
            "Release keystore does not exist: $releaseStoreFilePath"
        }
    }
}

tasks.matching { it.name == "preReleaseBuild" }.configureEach {
    dependsOn("checkReleaseSigning")
}

dependencies {
    implementation("androidx.activity:activity:1.13.0")
    implementation("androidx.core:core-ktx:1.17.0")
    testImplementation("junit:junit:4.13.2")
}
