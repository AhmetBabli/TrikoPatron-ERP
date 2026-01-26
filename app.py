import os
import sys
import webbrowser
from threading import Timer
from flask import Flask, render_template, request, redirect, url_for
import sqlite3
from datetime import datetime, timedelta

# --- 1. DOSYA YOLU AYARLARI (Senin EXE yapına özel) ---
if getattr(sys, 'frozen', False):
    # EXE çalışırken dosyaları geçici klasörden (_MEIPASS) alır
    TEMPLATE_KLASORU = os.path.join(sys._MEIPASS, 'templates')
    # Veritabanını ise EXE'nin yanına (Senin klasörüne) kaydeder
    DB_KLASORU = os.path.dirname(sys.executable)
else:
    # Normal çalışırken (VS Code)
    ANA_KLASOR = os.path.dirname(os.path.abspath(__file__))
    TEMPLATE_KLASORU = os.path.join(ANA_KLASOR, 'templates')
    DB_KLASORU = ANA_KLASOR

DB_YOLU = os.path.join(DB_KLASORU, 'triko_is_takip.db')

app = Flask(__name__, template_folder=TEMPLATE_KLASORU)
app.secret_key = 'triko_patron_gizli_anahtar_2026'

# --- 2. YARDIMCI FONKSİYON ---
def sayi_yap(deger):
    if not deger: return 0.0
    try: return float(str(deger).replace(',', '.').strip())
    except: return 0.0

# --- 3. VERİTABANI KONTROL ---
def veritabani_kontrol():
    try:
        with sqlite3.connect(DB_YOLU) as baglanti:
            imlec = baglanti.cursor()
            # İplik Giriş Defteri (Buradan ASLA silinmez)
            imlec.execute('''CREATE TABLE IF NOT EXISTS IPLIK_STOK (id INTEGER PRIMARY KEY AUTOINCREMENT, iplik_cinsi TEXT, renk TEXT, lot_no TEXT, cuval_adeti INTEGER, kilo_detaylari TEXT, toplam_kilo REAL, tarih TEXT)''')
            # Giden İş Ana Kaydı
            imlec.execute('''CREATE TABLE IF NOT EXISTS GIDEN_ISLER (id INTEGER PRIMARY KEY AUTOINCREMENT, model_adi TEXT, sure_dk REAL, dk_ucreti REAL, toplam_adet INTEGER, toplam_kilo REAL, toplam_tutar REAL, tarih TEXT)''')
            # İşin İçindeki Renk Detayları (Buradaki kilolar stoktan düşülecek miktar)
            imlec.execute('''CREATE TABLE IF NOT EXISTS IS_RENKLER (id INTEGER PRIMARY KEY AUTOINCREMENT, is_id INTEGER, renk TEXT, adet INTEGER, kilo REAL, FOREIGN KEY(is_id) REFERENCES GIDEN_ISLER(id))''')
            # Kasa Hareketleri
            imlec.execute('''CREATE TABLE IF NOT EXISTS ALINAN_ODEMELER (id INTEGER PRIMARY KEY AUTOINCREMENT, aciklama TEXT, tutar REAL, tarih TEXT)''')
            imlec.execute('''CREATE TABLE IF NOT EXISTS GIDERLER (id INTEGER PRIMARY KEY AUTOINCREMENT, gider_turu TEXT, aciklama TEXT, tutar REAL, tarih TEXT)''')
            baglanti.commit()
    except Exception as e: print(f"Veritabanı Hatası: {e}")

veritabani_kontrol()

# --- 4. HESAPLAMA MOTORU (STOK MANTIĞI BURADA) ---
def hesap_ozeti():
    try:
        with sqlite3.connect(DB_YOLU) as baglanti:
            imlec = baglanti.cursor()
            
            # Muhasebe
            top_is = imlec.execute("SELECT SUM(toplam_tutar) FROM GIDEN_ISLER").fetchone()[0] or 0
            top_tahsilat = imlec.execute("SELECT SUM(tutar) FROM ALINAN_ODEMELER").fetchone()[0] or 0
            top_gider = imlec.execute("SELECT SUM(tutar) FROM GIDERLER").fetchone()[0] or 0
            
            # --- YENİ STOK HESABI ---
            # 1. Bugüne kadar kapıdan içeri giren TOPLAM İPLİK
            toplam_giren = imlec.execute("SELECT SUM(toplam_kilo) FROM IPLIK_STOK").fetchone()[0] or 0
            
            # 2. Bugüne kadar işlere harcanan TOPLAM İPLİK
            toplam_harcanan = imlec.execute("SELECT SUM(kilo) FROM IS_RENKLER").fetchone()[0] or 0
            
            # 3. Elde Kalan (Güncel)
            guncel_stok = toplam_giren - toplam_harcanan
            
        return (top_is - top_tahsilat), (top_tahsilat - top_gider), guncel_stok
    except: return 0, 0, 0

# --- 5. ROTALAR ---
@app.route('/')
def ana_menu():
    alacak, kasa, stok = hesap_ozeti()
    # Stok değişkeni artık "Güncel Stok"u gösteriyor
    return render_template('menu.html', alacak=alacak, kasa=kasa, stok=stok)

@app.route('/iplik-gir', methods=['GET', 'POST'])
def iplik_gir():
    mesaj = ""
    if request.method == 'POST':
        try:
            cins = request.form.get('iplik_cinsi', '').upper()
            renk = request.form.get('renk', '').upper()
            lot = request.form.get('lot_no', '')
            try: cuval = int(request.form.get('cuval_adeti') or 0)
            except: cuval = 0
            
            tur = request.form.get('giris_turu')
            if tur == 'toplu':
                toplam_kilo = sayi_yap(request.form.get('manuel_toplam_kilo'))
                detay = "Toplu Giriş"
            else:
                kilo_listesi = [sayi_yap(k) for k in request.form.getlist('kilo[]') if k]
                toplam_kilo = sum(kilo_listesi)
                detay = "+".join(str(k) for k in kilo_listesi)
                if cuval == 0: cuval = len(kilo_listesi)
            
            bugun = datetime.now().strftime("%d.%m.%Y")
            
            with sqlite3.connect(DB_YOLU) as baglanti:
                baglanti.cursor().execute('INSERT INTO IPLIK_STOK (iplik_cinsi, renk, lot_no, cuval_adeti, kilo_detaylari, toplam_kilo, tarih) VALUES (?, ?, ?, ?, ?, ?, ?)', 
                                          (cins, renk, lot, cuval, detay, toplam_kilo, bugun))
                baglanti.commit()
            mesaj = "✅ İplik Depoya Girdi!"
        except Exception as e: mesaj = f"HATA: {e}"
    return render_template('iplik_gir.html', mesaj=mesaj)

@app.route('/iplik-listesi')
def iplik_listesi():
    try:
        with sqlite3.connect(DB_YOLU) as baglanti:
            imlec = baglanti.cursor()
            # Listede sadece girişleri görüyoruz
            veriler = imlec.execute("SELECT * FROM IPLIK_STOK ORDER BY id DESC").fetchall()
            
            # ÖZET HESAPLAMA
            toplam_giren = sum(row[6] for row in veriler) # 6.sütun toplam_kilo
            toplam_cuval = sum(row[4] for row in veriler)
            
            # Harcanan Hesapla
            toplam_harcanan = imlec.execute("SELECT SUM(kilo) FROM IS_RENKLER").fetchone()[0] or 0
            
            # Kalan Hesapla
            kalan = toplam_giren - toplam_harcanan

            # Renk bazlı gruplama (İsteğe bağlı görünüm için)
            renk_ozeti = {}
            for row in veriler:
                r = row[2].strip().upper()
                renk_ozeti[r] = renk_ozeti.get(r, 0) + row[6]

        return render_template('iplik_listesi.html', 
                               kayitlar=veriler, 
                               top_cuval=toplam_cuval, 
                               top_kilo=toplam_giren,  # DEPOYA GİREN TOPLAM
                               harcanan=toplam_harcanan, # İŞLERE GİDEN
                               kalan=kalan,           # ELDE KALAN (GÜNCEL)
                               renk_ozeti=renk_ozeti)
    except: return "Liste Hatası"

@app.route('/sil-iplik/<int:id>')
def sil_iplik(id):
    with sqlite3.connect(DB_YOLU) as baglanti:
        baglanti.cursor().execute("DELETE FROM IPLIK_STOK WHERE id=?", (id,))
        baglanti.commit()
    return redirect('/iplik-listesi')

@app.route('/giden-is-ekle', methods=['GET', 'POST'])
def giden_is_ekle():
    mesaj = ""
    if request.method == 'POST':
        try:
            model = request.form['model_adi'].upper()
            sure = sayi_yap(request.form['sure_dk'])
            ucret = sayi_yap(request.form['dk_ucreti'])
            
            renkler = request.form.getlist('renk[]')
            adetler = request.form.getlist('adet[]')
            kilolar = request.form.getlist('kilo[]')
            
            top_adet = sum([int(a) for a in adetler if a])
            top_kilo = sum([sayi_yap(k) for k in kilolar if k])
            tutar = top_adet * sure * ucret
            bugun = datetime.now().strftime("%d.%m.%Y")
            
            with sqlite3.connect(DB_YOLU) as baglanti:
                imlec = baglanti.cursor()
                imlec.execute('INSERT INTO GIDEN_ISLER (model_adi, sure_dk, dk_ucreti, toplam_adet, toplam_kilo, toplam_tutar, tarih) VALUES (?, ?, ?, ?, ?, ?, ?)', 
                              (model, sure, ucret, top_adet, top_kilo, tutar, bugun))
                yeni_id = imlec.lastrowid
                
                for i in range(len(renkler)):
                    if renkler[i]:
                        # Sadece kaydet, stoktan silme yok (Hesaplama otomatik yapılıyor)
                        imlec.execute('INSERT INTO IS_RENKLER (is_id, renk, adet, kilo) VALUES (?, ?, ?, ?)', 
                                      (yeni_id, renkler[i].upper(), int(adetler[i]), sayi_yap(kilolar[i])))
                baglanti.commit()
            mesaj = f"✅ İş Kaydedildi! (Stoktan otomatik düştü)"
        except: mesaj = "HATA"
    return render_template('giden_is.html', mesaj=mesaj)

@app.route('/giden-is-listesi')
def giden_is_listesi():
    try:
        with sqlite3.connect(DB_YOLU) as baglanti:
            fisler = baglanti.cursor().execute("SELECT * FROM GIDEN_ISLER ORDER BY id DESC").fetchall()
            detaylar = baglanti.cursor().execute("SELECT * FROM IS_RENKLER").fetchall()
        detay_dict = {}
        for d in detaylar:
            if d[1] not in detay_dict: detay_dict[d[1]] = []
            detay_dict[d[1]].append(d)
        return render_template('giden_is_listesi.html', fisler=fisler, detaylar=detay_dict)
    except: return "Liste Hatası"

@app.route('/sil-fis/<int:id>')
def sil_fis(id):
    with sqlite3.connect(DB_YOLU) as baglanti:
        # Fiş silinince harcanan iplik "boşa çıkar", yani stok geri artar (Otomatik)
        baglanti.cursor().execute("DELETE FROM IS_RENKLER WHERE is_id=?", (id,))
        baglanti.cursor().execute("DELETE FROM GIDEN_ISLER WHERE id=?", (id,))
        baglanti.commit()
    return redirect('/giden-is-listesi')

@app.route('/gider-ekle', methods=['GET', 'POST'])
def gider_ekle():
    mesaj = ""
    if request.method == 'POST':
        try:
            tur = request.form.get('gider_turu')
            acik = request.form.get('aciklama').upper()
            tut = sayi_yap(request.form.get('tutar'))
            with sqlite3.connect(DB_YOLU) as baglanti:
                baglanti.cursor().execute('INSERT INTO GIDERLER (gider_turu, aciklama, tutar, tarih) VALUES (?, ?, ?, ?)', 
                                          (tur, acik, tut, datetime.now().strftime("%d.%m.%Y")))
                baglanti.commit()
            mesaj = "✅ Gider Kaydedildi."
        except: mesaj = "HATA"
    return render_template('gider_ekle.html', mesaj=mesaj)

@app.route('/tahsilat-ekle', methods=['GET', 'POST'])
def tahsilat_ekle():
    mesaj = ""
    if request.method == 'POST':
        try:
            acik = request.form.get('aciklama').upper()
            tut = sayi_yap(request.form.get('tutar'))
            with sqlite3.connect(DB_YOLU) as baglanti:
                baglanti.cursor().execute('INSERT INTO ALINAN_ODEMELER (aciklama, tutar, tarih) VALUES (?, ?, ?)', 
                                          (acik, tut, datetime.now().strftime("%d.%m.%Y")))
                baglanti.commit()
            mesaj = "✅ Tahsilat Alındı."
        except: mesaj = "HATA"
    return render_template('tahsilat_ekle.html', mesaj=mesaj)

@app.route('/haftalik-hesap')
def haftalik_hesap():
    try:
        with sqlite3.connect(DB_YOLU) as baglanti:
            odeme = baglanti.cursor().execute("SELECT * FROM ALINAN_ODEMELER ORDER BY id DESC").fetchall()
            gider = baglanti.cursor().execute("SELECT * FROM GIDERLER ORDER BY id DESC").fetchall()
        bugun = datetime.now()
        hafta_basi = (bugun - timedelta(days=bugun.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        h_ode, t_ode = [], 0
        for x in odeme:
            if datetime.strptime(x[3], "%d.%m.%Y") >= hafta_basi: h_ode.append(x); t_ode += x[2]
        h_gid, t_gid = [], 0
        for x in gider:
            if datetime.strptime(x[4], "%d.%m.%Y") >= hafta_basi: h_gid.append(x); t_gid += x[3]
        return render_template('haftalik.html', baslangic=hafta_basi.strftime("%d.%m.%Y"), odemeler=h_ode, top_odeme=t_ode, giderler=h_gid, top_gider=t_gid, net=(t_ode - t_gid))
    except: return "Rapor Hatası"

def tarayici_ac(): webbrowser.open_new("http://127.0.0.1:5000")

if __name__ == '__main__':
    # EXE olduğunda tarayıcıyı otomatik açar
    Timer(1, tarayici_ac).start()
    app.run(host='0.0.0.0', port=5000, debug=False)