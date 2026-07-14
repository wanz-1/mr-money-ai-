# Mr Money AI - Play Store Deployment Guide

## Prerequisites
1. Google Play Developer Account ($25 one-time fee)
2. Android Studio installed
3. Java JDK 11+ installed
4. Signed keystore file

## Step 1: Generate APK/AAB

### Setup Java Environment
1. Download JDK 11+ from https://adoptium.net/
2. Install and set JAVA_HOME environment variable
3. Add to PATH: `%JAVA_HOME%\bin`

### Setup Android SDK
1. Download Android Studio from https://developer.android.com/studio
2. Install Android SDK 33
3. Set ANDROID_HOME to `C:\Users\<username>\AppData\Local\Android\Sdk`

### Build Release AAB
```bash
cd android
gradlew.bat assembleRelease
```

### Create Signed AAB for Play Store
```bash
cd android
keytool -genkey -v -keystore mr-money-ai.keystore -alias mr-money-ai -keyalg RSA -keysize 2048 -validity 10000
gradlew.bat bundleRelease
```

Output: `android/app/build/outputs/bundle/release/app-release.aab`

## Step 2: Play Store Listing

### Store Listing
- **App Name**: Mr Money AI
- **Short Description**: AI Document Intelligence Platform
- **Full Description**:
  ```
  Mr Money AI is a powerful document intelligence platform that helps you:
  
  • Analyze writing quality and style
  • Detect AI-generated content
  • Check for plagiarism and similarity
  • Review citations and references
  • Get actionable feedback for improvement
  
  Features:
  • 17 specialized analysis agents
  • Real-time collaboration
  • Document comparison
  • Multiple export formats (PDF, DOCX, Markdown)
  • Privacy-first approach
  
  Perfect for writers, students, researchers, and professionals.
  ```

### Graphics Assets
- **Hi-res icon**: 512x512 PNG (use generated icon)
- **Feature graphic**: 1024x500 PNG
- **Screenshots**: 
  - Phone: 16:9 or 9:16 ratio, min 320px, max 3840px
  - Tablet: 16:9 or 9:16 ratio, min 320px, max 3840px
  - Minimum 2 screenshots required

### Content Rating
- Complete IARC questionnaire
- Target audience: General (13+)

### Pricing & Distribution
- Free
- Available in all countries
- Contains ads: No
- Contains in-app purchases: No

## Step 3: Upload to Play Console

1. Go to https://play.google.com/console
2. Create new app
3. Complete store listing
4. Upload AAB file
5. Set pricing (Free)
6. Complete content rating
7. Submit for review

## Step 4: Post-Launch

### Monitor Performance
- Check crash reports in Play Console
- Monitor user reviews
- Track installation metrics

### Update Process
1. Update version in `android/app/build.gradle`
2. Build new AAB
3. Upload to Play Console
4. Roll out gradually (10% → 50% → 100%)

## Troubleshooting

### Build Fails
- Ensure JAVA_HOME is set correctly
- Run `gradlew.bat clean` before rebuild
- Check Android SDK is installed

### Upload Fails
- Verify AAB is signed with release keystore
- Check version code is higher than previous release
- Ensure all required graphics are uploaded

### Review Rejected
- Check content rating is accurate
- Ensure privacy policy URL is accessible
- Verify app doesn't violate content policies
