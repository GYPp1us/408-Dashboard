plugins {
    id("com.android.application")
}

providers.gradleProperty("atomicLabBuildDir").orNull?.let {
    layout.buildDirectory.set(file(it))
}

android {
    namespace = "com.mutsumi.focus.atomiclab"
    compileSdk = 36
    defaultConfig {
        applicationId = providers.gradleProperty("atomicLabPackage").orNull
            ?: "com.mutsumi.focus.atomiclab"
        minSdk = 33
        targetSdk = 36
        versionCode = 2
        versionName = "0.2-local"
    }
    // Share the protocol builder with the actual timer, without loading its UI,
    // server connection, account data, or foreground service in the experiment.
    sourceSets.getByName("main").java.srcDir("../app/src/main/java/com/mutsumi/focus/atomic")
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

androidComponents {
    beforeVariants(selector().withBuildType("release")) { it.enable = false }
}
