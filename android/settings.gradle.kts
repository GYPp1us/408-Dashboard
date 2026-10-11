pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
        maven("https://jitpack.io") {
            content { includeModule("com.github.Flyfish233", "spake2-java") }
        }
    }
}

rootProject.name = "MutsumiFocus"
include(":app")
include(":atomic-lab")
