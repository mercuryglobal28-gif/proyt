# YouTroc Proxy Pool

مشروع مستقل يجمع بروكسيات HTTP عامة، يتحقق من HTTPS CONNECT إلى YouTube، ويصدر ملف JSON مرتبًا بزمن الاستجابة. التطبيق يعيد الفحص من شبكة المستخدم ويختار الأسرع محليًا. لا توجد حاجة إلى التلفاز لتشغيل المشروع.

## التشغيل

المتطلبات: Python 3.11 أو أحدث، وcurl 8 أو أحدث. لا توجد حزم pip مطلوبة.

```bash
python -m unittest discover -s tests -v
python src/proxy_pool.py
```

الناتج `public/proxies.json`. تجربة محدودة:

```bash
python src/proxy_pool.py --limit 24 --workers 6 --timeout 5
```

الافتراضي: عينة عشوائية تصل إلى 400 عنوان، 12 مهمة متزامنة، مهلة 8 ثوانٍ لكل طلب، وطلبان ناجحان إلزاميان إلى `https://www.youtube.com/generate_204` لكل بروكسي. العنوان الذي لا يعيد 204 بجسم فارغ عبر TLS صالح يُستبعد. المصادر من Proxifly وTheSpeedX؛ المصدر ليس ضمانًا لعمل عناوينه. يتم حذف التكرار ورفض العناوين المحلية والخاصة والمحجوزة وأسماء النطاقات وبيانات تسجيل الدخول. الإصدار الأول يدعم HTTP CONNECT عبر IPv4 فقط، وهو متوافق مع ProxyProtocol.HTTP في التطبيق.

## قياس السرعة

- `latency_ms`: وسيط زمن طلب HTTPS كامل، يشمل تأسيس الاتصال والنفق وTLS، وليس ICMP ping.
- `ttfb_ms`: وسيط الوقت حتى أول بايت.
- `download_mbps`: معدل تنزيل عينة 64 KiB من Cloudflare محسوبًا بالميغابت/ثانية؛ `null` عندما لم ينجح القياس أو تم تعطيله.
- `speed_test_ok`: نجاح طلب العينة بالحجم والحالة المتوقعين.
- الترتيب بزمن الاستجابة أولًا. معدل التنزيل تقدير قصير قد يتأثر بالتوازي وموقع الخادم؛ ليس ضمانًا لسرعة فيديو YouTube أو تجاوز قيود الفيديو الإقليمية.
- صلاحية كل نتيجة ساعتان. لا يتم تجديد صلاحية عنوان قديم دون فحصه مجددًا.

## النشر إلى GitHub

المستودع المستهدف: https://github.com/mercuryglobal28-gif/proyt

ضع ملفات المشروع على الفرع الافتراضي. شغّل **Actions → Refresh proxy pool → Run workflow** لأول نتيجة. ينفذ workflow تحديثًا كل ساعة عند الدقيقة 17 UTC، وينشر `proxies.json` في فرع مستقل اسمه `data`، ولا يخلط تحديثات البيانات مع كود المشروع.

رابط JSON بعد نجاح أول تشغيل، إذا كان المستودع عامًا:

```
https://raw.githubusercontent.com/mercuryglobal28-gif/proyt/data/proxies.json
```

يستخدم `GITHUB_TOKEN` التلقائي بصلاحية `contents: write`؛ لا يحتاج PAT داخل الكود. قد تمنع قواعد المؤسسة أو حماية فرع data الكتابة؛ عندها تظهر رسالة خطأ في تشغيل Actions. لن يستطيع تطبيق عام قراءة مستودع خاص دون مصادقة، ولا يجوز تضمين رمز وصول GitHub في التطبيق.

جدولة GitHub ليست ضمانًا لموعد دقيق وقد تتأخر أو تتوقف مع الخمول بحسب إعدادات GitHub؛ يجب على التطبيق الالتزام بـ expires_at. تعطل تشغيل كامل يبقي الملف القديم بطابعه القديم، وفشل المصادر داخل تشغيل مكتمل ينشر قائمة فارغة بحالة واضحة بدل إظهار بيانات قديمة على أنها جديدة.

## عقد البيانات والدمج

راجع [عقد التطبيق](docs/APP_INTEGRATION_AR.md) و[JSON Schema](docs/proxies.schema.json). حالات الملف: `ok` أو `degraded` أو `no_working_proxies` أو `sources_unavailable`. لا يعني نجاح التشغيل وجود بروكسيات تعمل؛ قد تكون القائمة فارغة.

لا يغيّر المشروع تطبيق YouTroc تلقائيًا. أبقِ OAuth والحسابات وبيانات الدخول خارج البروكسي العام وفق سياسة ProxyAuthIsolationPolicy الموجودة. لا يُعطّل التحقق من TLS ولا يُسمح بالتحويلات أو السقوط إلى اتصال مباشر أثناء قياس البروكسي.

## مصادر مرجعية

- [مصدر Proxifly](https://github.com/proxifly/free-proxy-list) — القائمة `proxies/protocols/http/data.txt`.
- [مصدر TheSpeedX](https://github.com/TheSpeedX/PROXY-List) — القائمة `http.txt`.
- [توثيق curl وخيارات القياس](https://curl.se/docs/manpage.html).
- [جدولة GitHub Actions](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).
