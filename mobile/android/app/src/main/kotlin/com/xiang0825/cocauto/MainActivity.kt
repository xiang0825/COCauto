package com.xiang0825.cocauto

import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.PackageManager
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.embedding.android.FlutterActivity
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    companion object {
        private const val CHANNEL = "com.xiang0825.cocauto/game"
        private const val COC_PACKAGE = "com.supercell.clashofclans"
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, CHANNEL)
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "isGameInstalled" -> result.success(isGameInstalled())
                    "launchGame" -> launchGame(result)
                    "appVersion" -> {
                        val info = packageManager.getPackageInfo(packageName, 0)
                        val build = if (android.os.Build.VERSION.SDK_INT >= 28) {
                            info.longVersionCode
                        } else {
                            @Suppress("DEPRECATION")
                            info.versionCode.toLong()
                        }
                        result.success("${info.versionName ?: "unknown"}-rc$build")
                    }
                    else -> result.notImplemented()
                }
            }
    }

    private fun isGameInstalled(): Boolean = try {
        packageManager.getPackageInfo(COC_PACKAGE, 0)
        true
    } catch (_: PackageManager.NameNotFoundException) {
        false
    }

    private fun launchGame(result: MethodChannel.Result) {
        val intent = packageManager.getLaunchIntentForPackage(COC_PACKAGE)
        if (intent == null) {
            result.success(false)
            return
        }
        try {
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            startActivity(intent)
            result.success(true)
        } catch (_: ActivityNotFoundException) {
            result.success(false)
        }
    }
}
