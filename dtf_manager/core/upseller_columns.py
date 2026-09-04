UPSELLER_COLUMNS = {
    "platform_order_number": "Nº de Pedido da Plataforma",
    "upseller_order_number": "Nº de Pedido",
    "platform": "Plataformas",
    "store_name": "Nome da Loja no UpSeller",
    "product_name": "Nome do Anúncio",
    "listing_id": "ID do Anúncio",
    "sku": "SKU",
    "variation": "Variação",
    "variant_id": "ID da Variante",
    "product_image_url": "Link da Imagem",
    "product_price": "Preço de Produto",
    "product_quantity": "Qtd. do Produto",
}

REQUIRED_UPSELLER_COLUMNS = (
    UPSELLER_COLUMNS["platform_order_number"],
    UPSELLER_COLUMNS["product_name"],
    UPSELLER_COLUMNS["listing_id"],
    UPSELLER_COLUMNS["sku"],
    UPSELLER_COLUMNS["variation"],
    UPSELLER_COLUMNS["product_quantity"],
)

