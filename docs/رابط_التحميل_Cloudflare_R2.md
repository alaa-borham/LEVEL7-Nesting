# رابط تحميل مستقل (Cloudflare R2)

بعد هذا الإعداد مرة واحدة: كل تحديث يُرفع تلقائيًا إلى مساحتك على Cloudflare، ويقرأ البرنامج التحديثات منها
أولًا (GitHub يبقى احتياطيًا فقط). الروابط التي تشاركها:

- صفحة التحميل: `https://<رابطك>/index.html`
- أحدث ملف تثبيت دائمًا: `https://<رابطك>/LEVEL7Nesting-Setup.exe`

## الخطوات (حوالي 10 دقائق)
1. أنشئ حسابًا مجانيًا على https://dash.cloudflare.com ثم افتح **R2 Object Storage** وفعّله
   (الخطة المجانية 10 جيجابايت؛ قد يطلب بطاقة للتفعيل دون خصم).
2. **Create bucket** باسم مثل `level7-downloads`.
3. داخل الـ bucket: **Settings ← Public access**:
   - إما **R2.dev subdomain ← Allow** فتحصل على رابط مثل `https://pub-xxxx.r2.dev`
   - أو **Custom domain** إذا كان لديك دومين على Cloudflare (مثل `download.level7.com`) — أفضل وأوضح.
4. **R2 ← Manage API tokens ← Create API token**: الصلاحية **Object Read & Write**، ومقيد بهذا الـ bucket فقط.
   انسخ **Access Key ID** و **Secret Access Key** (يظهر مرة واحدة)، وانسخ **Account ID** من صفحة R2.
5. في GitHub: المستودع ← **Settings ← Secrets and variables ← Actions**:
   - تبويب **Secrets** (سري): `R2_ACCESS_KEY_ID` و `R2_SECRET_ACCESS_KEY`
   - تبويب **Variables** (غير سري): `R2_ACCOUNT_ID` و `R2_BUCKET` (اسم الـ bucket) و `R2_PUBLIC_URL`
     (الرابط من الخطوة 3 بدون / في النهاية)
6. أخبرني عند الانتهاء؛ التحديث التالي يُرفع تلقائيًا وأتأكد أن الرابط يعمل.

> لا ترسل المفاتيح السرية في المحادثة؛ ضعها فقط في GitHub Secrets.

## كيف يعمل
- بعد نجاح البناء والاختبارات على Windows يرفع GitHub Actions: ملف التثبيت (برقم الإصدار + نسخة باسم ثابت)،
  ثم `index.html`، ثم `latest.json` أخيرًا (حتى لا يشير ملف التحديث إلى ملف غير موجود).
- البرنامج يقرأ `latest.json` من رابطك، ويقبل ملف التثبيت فقط من نفس الرابط وبنفس بصمة SHA-256.
- النسخ التي بُنيت قبل إعداد R2 تقرأ من GitHub، وتحصل على أول نسخة تعرف رابطك عبر GitHub مرة واحدة،
  وبعدها كل التحديثات من رابطك.
