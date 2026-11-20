use base64::{engine::general_purpose::STANDARD, Engine};
use std::io::{Cursor, Read};
use std::time::Duration;

const MAX_SIZE: usize = 256 * 1024;
const HOST: &str = "textures.minecraft.net/texture/";

fn texture_url(url: &str) -> Option<String> {
    let hash = url
        .strip_prefix("https://")
        .or_else(|| url.strip_prefix("http://"))?
        .strip_prefix(HOST)?;
    (matches!(hash.len(), 32..=64) && hash.bytes().all(|b| b.is_ascii_hexdigit()))
        .then(|| format!("https://{HOST}{hash}"))
}

pub(super) fn fetch(url: Option<&str>) -> Option<String> {
    let url = texture_url(url?)?;
    let response = ureq::AgentBuilder::new()
        .redirects(0)
        .timeout(Duration::from_secs(4))
        .build()
        .get(&url)
        .call()
        .ok()?;
    if response.status() != 200 {
        return None;
    }
    let mut skin = Vec::new();
    response
        .into_reader()
        .take((MAX_SIZE + 1) as u64)
        .read_to_end(&mut skin)
        .ok()?;
    (skin.len() <= MAX_SIZE).then_some(())?;
    Some(format!(
        "data:image/png;base64,{}",
        STANDARD.encode(face(&skin)?)
    ))
}

fn face(skin: &[u8]) -> Option<Vec<u8>> {
    let mut decoder =
        png::Decoder::new_with_limits(Cursor::new(skin), png::Limits { bytes: MAX_SIZE });
    decoder.set_transformations(png::Transformations::normalize_to_color8());
    let info = decoder.read_header_info().ok()?;
    if info.width != 64 || !matches!(info.height, 32 | 64) {
        return None;
    }
    let mut reader = decoder.read_info().ok()?;
    let mut pixels = vec![0; reader.output_buffer_size()?];
    let frame = reader.next_frame(&mut pixels).ok()?;
    let samples = frame.color_type.samples();
    let pixel = |x, y| {
        let i = y * frame.line_size + x * samples;
        match &pixels[i..i + samples] {
            &[g] => [g, g, g, 255],
            &[g, a] => [g, g, g, a],
            &[r, g, b] => [r, g, b, 255],
            &[r, g, b, a] => [r, g, b, a],
            _ => unreachable!(),
        }
    };
    let mut head = Vec::with_capacity(8 * 8 * 3);
    for y in 8..16 {
        for x in 8..16 {
            let base = pixel(x, y);
            let overlay = pixel(x + 32, y);
            let a = u16::from(overlay[3]);
            for i in 0..3 {
                head.push(
                    ((u16::from(overlay[i]) * a + u16::from(base[i]) * (255 - a) + 127) / 255)
                        as u8,
                );
            }
        }
    }
    let mut output = Vec::new();
    let mut encoder = png::Encoder::new(&mut output, 8, 8);
    encoder.set_color(png::ColorType::Rgb);
    encoder.write_header().ok()?.write_image_data(&head).ok()?;
    Some(output)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_fixed_mojang_texture_paths_are_fetched() {
        let hash = "f".repeat(64);
        assert_eq!(
            texture_url(&format!("http://{HOST}{hash}")),
            Some(format!("https://{HOST}{hash}"))
        );
        assert!(texture_url(&format!("https://{HOST}{hash}?token=x")).is_none());
        assert!(texture_url(&format!("https://evil.test/{HOST}{hash}")).is_none());
    }

    #[test]
    fn avatar_crops_the_head_and_composites_the_hat() {
        for height in [32, 64] {
            let mut skin = vec![0; 64 * height * 4];
            for (x, color) in [
                (8, [200, 100, 50, 255]),
                (40, [0, 200, 150, 128]),
                (9, [20, 30, 40, 255]),
            ] {
                let i = (8 * 64 + x) * 4;
                skin[i..i + 4].copy_from_slice(&color);
            }
            let mut png = Vec::new();
            let mut enc = png::Encoder::new(&mut png, 64, height as u32);
            enc.set_color(png::ColorType::Rgba);
            enc.write_header().unwrap().write_image_data(&skin).unwrap();
            let decoded = face(&png).unwrap();
            let mut reader = png::Decoder::new(Cursor::new(decoded)).read_info().unwrap();
            let mut head = [0; 8 * 8 * 3];
            let info = reader.next_frame(&mut head).unwrap();
            assert_eq!([info.width, info.height], [8, 8]);
            assert_eq!(&head[..6], &[100, 150, 100, 20, 30, 40]);
        }
        assert!(face(b"not a PNG").is_none());
    }
}
