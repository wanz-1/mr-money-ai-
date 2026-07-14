# HumanProof AI - Android App

## Build with Android Studio

1. Open `android/` folder in Android Studio
2. Let Gradle sync
3. Build > Build Bundle(s) / APK(s) > Build APK(s)
4. APK will be in `app/build/outputs/apk/release/`

## Build with Command Line

```bash
cd android
./gradlew assembleRelease
```

## Play Store Upload

1. Build a signed AAB: `./gradlew bundleRelease`
2. Upload to [Play Console](https://play.google.com/console)
3. The app loads your deployed HumanProof AI instance

## Configuration

Edit `MainActivity.java` to change the URL your app loads:
```java
webView.loadUrl("https://your-deployment-url.onrender.com");
```
