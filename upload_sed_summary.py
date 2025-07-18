#!/usr/bin/env python3
"""
SEDサマリーアップロードツール

ローカルに保存されたSEDサマリーファイルを
Vault APIにアップロードする。
"""

import asyncio
import aiohttp
import json
import os
import ssl
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import argparse
import logging
from datetime import datetime


class SEDSummaryUploader:
    """SEDサマリーアップロードクラス"""
    
    def __init__(self, upload_url: str = "https://api.hey-watch.me/upload/analysis/sed-summary", verify_ssl: bool = True):
        self.upload_url = upload_url
        self.base_dir = Path("/Users/kaya.matsumoto/data/data_accounts")
        self.verify_ssl = verify_ssl
        
        # SSL設定を準備
        if not self.verify_ssl:
            self.ssl_context = ssl.create_default_context()
            self.ssl_context.check_hostname = False
            self.ssl_context.verify_mode = ssl.CERT_NONE
        else:
            self.ssl_context = None
        
        # ログ設定
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
    
    def find_all_summary_files(self) -> List[Tuple[str, str, Path]]:
        """
        ベースディレクトリ配下の全SEDサマリーファイルを探索
        Returns: [(device_id, date, file_path), ...]
        """
        summary_files = []
        
        if not self.base_dir.exists():
            self.logger.warning(f"ベースディレクトリが存在しません: {self.base_dir}")
            return summary_files
        
        # パターン: /Users/kaya.matsumoto/data/data_accounts/{device_id}/{YYYY-MM-DD}/sed-summary/result.json
        for device_dir in self.base_dir.iterdir():
            if not device_dir.is_dir():
                continue
                
            device_id = device_dir.name
            
            for date_dir in device_dir.iterdir():
                if not date_dir.is_dir():
                    continue
                
                date = date_dir.name
                
                # 日付形式の検証
                try:
                    datetime.strptime(date, "%Y-%m-%d")
                except ValueError:
                    continue
                
                summary_file = date_dir / "sed-summary" / "result.json"
                if summary_file.exists():
                    summary_files.append((device_id, date, summary_file))
                    self.logger.debug(f"発見: {device_id}/{date} - {summary_file}")
        
        self.logger.info(f"合計 {len(summary_files)} 個のサマリーファイルを発見")
        return summary_files
    
    def find_summary_file(self, device_id: str, date: str) -> Optional[Path]:
        """
        特定のデバイス・日付のサマリーファイルを取得
        """
        file_path = self.base_dir / device_id / date / "sed-summary" / "result.json"
        
        if file_path.exists():
            return file_path
        else:
            self.logger.warning(f"ファイルが存在しません: {file_path}")
            return None
    
    async def upload_summary_file(self, session: aiohttp.ClientSession, 
                                 device_id: str, date: str, file_path: Path) -> bool:
        """
        単一のサマリーファイルをアップロード
        """
        try:
            self.logger.info(f"アップロード開始: {device_id}/{date}")
            
            # ファイル読み込み
            with open(file_path, 'r', encoding='utf-8') as f:
                file_content = f.read()
            
            # フォームデータ作成
            form_data = aiohttp.FormData()
            form_data.add_field('file', file_content, 
                              filename='result.json', 
                              content_type='application/json')
            form_data.add_field('device_id', device_id)
            form_data.add_field('date', date)
            
            # アップロード実行
            async with session.post(
                self.upload_url,
                data=form_data,
                timeout=aiohttp.ClientTimeout(total=60)
            ) as response:
                
                if response.status == 200:
                    self.logger.info(f"✅ アップロード成功: {device_id}/{date}")
                    return True
                else:
                    error_text = await response.text()
                    self.logger.error(f"❌ アップロード失敗: {device_id}/{date} - "
                                    f"HTTP {response.status}: {error_text}")
                    return False
                    
        except aiohttp.ClientError as e:
            self.logger.error(f"❌ 接続エラー: {device_id}/{date} - {e}")
            return False
        except json.JSONDecodeError as e:
            self.logger.error(f"❌ JSON解析エラー: {device_id}/{date} - {e}")
            return False
        except FileNotFoundError:
            self.logger.error(f"❌ ファイルが見つかりません: {file_path}")
            return False
        except Exception as e:
            self.logger.error(f"❌ 予期しないエラー: {device_id}/{date} - {e}")
            return False
    
    async def upload_all_summaries(self) -> Dict[str, int]:
        """
        全てのサマリーファイルを並列アップロード
        """
        summary_files = self.find_all_summary_files()
        
        if not summary_files:
            self.logger.warning("アップロードするファイルがありません")
            return {"success": 0, "failed": 0, "total": 0}
        
        success_count = 0
        failed_count = 0
        
        # SSL設定を含むConnectorを作成
        connector = aiohttp.TCPConnector(
            ssl=self.ssl_context if not self.verify_ssl else True
        )
        
        async with aiohttp.ClientSession(connector=connector) as session:
            # 並列アップロード実行
            tasks = []
            for device_id, date, file_path in summary_files:
                task = self.upload_summary_file(session, device_id, date, file_path)
                tasks.append((device_id, date, task))
            
            # 結果収集
            for device_id, date, task in tasks:
                success = await task
                if success:
                    success_count += 1
                else:
                    failed_count += 1
        
        return {
            "success": success_count,
            "failed": failed_count,
            "total": len(summary_files)
        }
    
    async def upload_specific_summary(self, device_id: str, date: str) -> bool:
        """
        特定のデバイス・日付のサマリーファイルをアップロード
        """
        file_path = self.find_summary_file(device_id, date)
        
        if not file_path:
            self.logger.error(f"ファイルが存在しません: {device_id}/{date}")
            return False
        
        # SSL設定を含むConnectorを作成
        connector = aiohttp.TCPConnector(
            ssl=self.ssl_context if not self.verify_ssl else True
        )
        
        async with aiohttp.ClientSession(connector=connector) as session:
            return await self.upload_summary_file(session, device_id, date, file_path)
    
    async def run(self, device_id: Optional[str] = None, date: Optional[str] = None) -> Dict[str, int]:
        """
        メイン実行関数
        device_id, dateが指定されていれば特定ファイル、未指定なら全ファイル処理
        """
        self.logger.info("SEDサマリーアップロード開始")
        
        if device_id and date:
            # 特定ファイルのアップロード
            self.logger.info(f"特定ファイルをアップロード: {device_id}/{date}")
            success = await self.upload_specific_summary(device_id, date)
            return {
                "success": 1 if success else 0,
                "failed": 0 if success else 1,
                "total": 1
            }
        else:
            # 全ファイルのアップロード
            self.logger.info("全ファイルをアップロード")
            return await self.upload_all_summaries()


async def main():
    """コマンドライン実行用メイン関数"""
    parser = argparse.ArgumentParser(description="SEDサマリーアップロードツール")
    parser.add_argument("--device-id", help="特定デバイスID（指定時は --date も必須）")
    parser.add_argument("--date", help="特定日付（YYYY-MM-DD形式）")
    parser.add_argument("--upload-url", 
                       default="https://api.hey-watch.me/upload/analysis/sed-summary", 
                       help="アップロードURL")
    parser.add_argument("--verbose", "-v", action="store_true", help="詳細ログ出力")
    
    args = parser.parse_args()
    
    # ログレベル設定
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # 引数検証
    if (args.device_id and not args.date) or (not args.device_id and args.date):
        print("エラー: --device-id と --date は同時に指定してください")
        return
    
    if args.date:
        try:
            datetime.strptime(args.date, "%Y-%m-%d")
        except ValueError:
            print("エラー: 日付はYYYY-MM-DD形式で指定してください")
            return
    
    # アップロード実行
    uploader = SEDSummaryUploader(args.upload_url)
    result = await uploader.run(args.device_id, args.date)
    
    # 結果出力
    print(f"\n📊 アップロード結果")
    print(f"✅ 成功: {result['success']} ファイル")
    print(f"❌ 失敗: {result['failed']} ファイル")
    print(f"📁 合計: {result['total']} ファイル")
    
    if result['total'] > 0:
        success_rate = (result['success'] / result['total']) * 100
        print(f"🎯 成功率: {success_rate:.1f}%")
    
    if result['success'] > 0:
        print(f"\n🎉 アップロード完了")
    elif result['total'] == 0:
        print(f"\n⚠️ アップロード対象ファイルなし")
    else:
        print(f"\n❌ アップロード失敗")


if __name__ == "__main__":
    asyncio.run(main()) 