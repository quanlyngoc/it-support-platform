# ADR-0015: Đăng nhập SSO bằng OpenID Connect + công tắc bật/tắt LDAP và SSO

- Ngày: 12/10/2026
- Trạng thái: Đã duyệt (yêu cầu của người phụ trách dự án khi làm Sổ tay 8.3: "thêm cấu hình cơ chế đăng nhập SSO … nút
  gạt để on/off 2 cơ chế đăng nhập — không cần LDAP thì gạt off, SSO cũng tương tự")

## Bối cảnh
Hệ cũ chỉ có tài khoản Local và AD (bind LDAP bằng mật khẩu AD). Đặc tả SaaS chưa có SSO. Trường dùng Microsoft 365, nên
người dùng muốn đăng nhập IT Monitor bằng tài khoản Microsoft (kèm MFA của Microsoft), và muốn tắt hẳn LDAP khi không cần.

## Quyết định
1. **Ba cơ chế theo tổ chức:** Local (LUÔN BẬT — Super Admin là tài khoản Local, tắt được là có thể tự khoá mình ra
   ngoài) · LDAP/AD (công tắc `ldap.enabled`; chưa từng gạt = bật, giữ hành vi cũ) · SSO (công tắc `sso.enabled`, mặc
   định tắt). Lưu trong `settings` của tổ chức; bí mật (`ldap.bind_pass_enc`, `sso.client_secret_enc`) mã hoá AES-GCM.
2. **SSO = OpenID Connect, Authorization Code + PKCE + nonce, Core là confidential client.** Chuẩn mở, chạy được với
   Microsoft Entra ID, Google Workspace, Keycloak… — không gắn một nhà cung cấp.
3. **Trao phiên về Desktop bằng HỎI LẠI (poll):** Desktop gọi `/api/auth/sso/start` (nhận `login_id` bí mật + `auth_url`),
   mở `auth_url` bằng TRÌNH DUYỆT HỆ THỐNG, rồi hỏi `/api/auth/sso/poll` mỗi 1,5 s; nhà cung cấp chuyển trình duyệt về
   `GET /api/auth/sso/callback` của Core. Token phiên Core trao MỘT lần rồi xoá bản ghi (`sso_logins`, TTL).
4. **Không tự tạo tài khoản:** định danh SSO (claim cấu hình được, mặc định `preferred_username`) phải ghép được với tài
   khoản ĐÃ đăng ký: AD theo tên / UPN / email → Local theo email → AD trùng phần trước @ (duy nhất). Tùy chọn giới hạn
   tên miền. Giống hệ cũ: AD chưa đăng ký là từ chối.
5. **ID token không kiểm chữ ký:** nhận trực tiếp từ token endpoint qua TLS (OIDC Core 3.1.3.7 mục 6) — kiểm `iss`,
   `aud`, `exp`, `nonce`. Issuer bắt buộc `https://` (trừ 127.0.0.1/localhost để thử).
6. **SSO không đòi TOTP của Core** (MFA do nhà cung cấp lo); vẫn áp giới hạn IP theo tài khoản + một thiết bị/một lúc.

## Phương án đã loại
- **Deep link / custom URL scheme (`itmonitor://callback`)**: phải đăng ký scheme trong Windows khi cài, mỗi nhà cung cấp
  xử lý custom scheme khác nhau, và Desktop phải nhận token qua tham số dòng lệnh — rắc rối hơn hỏi lại mà không an toàn hơn.
- **Cửa sổ WebView trong ứng dụng**: Microsoft khuyến cáo không đăng nhập trong WebView nhúng (không dùng được phiên/MFA
  sẵn có của trình duyệt, dễ bị chặn) — dùng trình duyệt hệ thống.
- **Kiểm chữ ký JWKS**: cần thêm thư viện JWT + đệm khoá; không cần với luồng code trực tiếp qua TLS. Có thể bổ sung sau
  nếu chuyển sang implicit/hybrid flow (không định làm).
- **SAML 2.0**: nặng hơn, cần XML-DSig; OIDC đủ cho mọi nhà cung cấp mà trường dùng.

## Hệ quả
- Đăng ký ứng dụng ở nhà cung cấp với Redirect URI = `<địa chỉ Core mà Desktop dùng>/api/auth/sso/callback` (hiện ở tab
  Quản trị → Đăng nhập). Microsoft Entra chỉ nhận `https://` (trừ localhost) → cần khối Caddy :7443 (Sổ tay 4.7).
- Callback là route công khai — chống giả mạo bằng `state` (chứa mã tổ chức + ngẫu nhiên), PKCE, `nonce`, hạn 10 phút.
- HOAN_BAO_MAT: khoá chủ mã hoá bí mật đang là khoá mặc định giai đoạn dựng thử; LDAPS chưa kiểm chứng chỉ (như hệ cũ).
