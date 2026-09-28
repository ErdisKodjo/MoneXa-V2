class ApiEndpoints {
  ApiEndpoints._();

  static const String token = '/api/auth/token/';
  static const String refresh = '/api/auth/refresh/';
  static const String me = '/api/auth/me/';
  static const String toggle2fa = '/api/auth/me/2fa/';
  static const String dashboard = '/api/dashboard/summary/';
  static const String payments = '/api/payments/';
  static const String evidence = '/api/payments/evidence/';
  static const String manualText = '/api/payments/manual-text/';
  static String validatePayment(int id) => '/api/payments/$id/validate/';
  static const String assistant = '/api/assistant/ask/';
  static const String forecast = '/api/reports/forecast/';

  // Factures (DRF paginé : {count, results})
  static const String invoices = '/api/invoices/';

  // Caisse POS (mobile)
  static const String caisseProduits = '/api/caisse/produits/';
  static const String caisseSession = '/api/caisse/session/';
  static const String caisseCloture = '/api/caisse/session/cloture/';
  static const String caisseVentes = '/api/caisse/ventes/';
}
